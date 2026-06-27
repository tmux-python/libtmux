"""fastmcp middleware for the engine-ops MCP server.

Ported from libtmux-mcp, adapted to the engine-ops adapter (the only
``libtmux_mcp`` dependency was the safety core, now :mod:`._safety`). In
outer-to-inner stack order:

* :class:`SafetyMiddleware` gates tools by safety tier (see :mod:`._safety`).
* :class:`ToolErrorResultMiddleware` converts tool-call failures into
  ``ToolResult(is_error=True)`` carrying the clean message + a structured
  ``meta`` payload, instead of fastmcp's ``-32603`` "Internal error: " catch-all.
* :class:`AuditMiddleware` emits one structured log record per tool call, with
  payload-bearing arguments redacted to a length + SHA-256 prefix.
* :class:`ReadonlyRetryMiddleware` retries transient libtmux failures, but only
  for readonly tools (re-running a mutating tool would double side effects).
* :class:`TailPreservingResponseLimitingMiddleware` caps oversized output while
  keeping the **tail** -- terminal scrollback's useful output is at the bottom.

This module is imported only from the fastmcp edge (the adapter builders), so it
imports the real fastmcp base classes at module top.
"""

from __future__ import annotations

import hashlib
import logging
import time
import typing as t

from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.middleware.error_handling import (
    ErrorHandlingMiddleware,
    RetryMiddleware,
)
from fastmcp.server.middleware.response_limiting import ResponseLimitingMiddleware
from fastmcp.tools.base import ToolResult
from mcp.types import CallToolRequestParams, TextContent
from pydantic import ValidationError as PydanticValidationError

from libtmux import exc as libtmux_exc
from libtmux.experimental.mcp._safety import (
    _TIER_LEVELS,
    TAG_READONLY,
    ExpectedToolError,
)

#: Curated scrollback tools whose output the tail-preserving limiter backstops.
#: Only terminal-text tools benefit; structured list/get responses stay under the
#: cap naturally.
_RESPONSE_LIMITED_TOOLS: tuple[str, ...] = (
    "capture_pane",
    "capture_active_pane",
    "grep_pane",
    "search_panes",
    "show_buffer",
    "capture_relative_pane",
    "grep_relative_pane",
)

#: Default byte ceiling -- matches fastmcp's stock 1 MB so normal schema-bearing
#: responses stay below this global backstop.
DEFAULT_RESPONSE_LIMIT_BYTES = 1_000_000


# ---------------------------------------------------------------------------
# Tool-error result conversion
# ---------------------------------------------------------------------------


def _schema_validation_error(
    error: BaseException,
) -> PydanticValidationError | None:
    """Return the Pydantic validation error behind a schema failure."""
    if isinstance(error, PydanticValidationError):
        return error
    cause = error.__cause__
    if isinstance(cause, PydanticValidationError):
        return cause
    return None


def _is_schema_validation_error(error: BaseException) -> bool:
    """Return True for fastmcp argument-schema validation failures.

    fastmcp validates tool arguments against the input schema *before* tool code
    runs, raising a bare :exc:`pydantic.ValidationError`. Bad arguments are
    agent-correctable, so they get the same expected/WARNING treatment as
    :class:`~._safety.ExpectedToolError`.
    """
    return _schema_validation_error(error) is not None


def _validation_errors_without_inputs(
    error: PydanticValidationError,
) -> list[dict[str, t.Any]]:
    """Return validation errors without rejected input values."""
    return t.cast(
        "list[dict[str, t.Any]]",
        error.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        ),
    )


def _format_schema_validation_error(error: BaseException) -> str:
    """Format a Pydantic validation error without raw input values."""
    err = _schema_validation_error(error)
    if err is None:
        return str(error)
    count = err.error_count()
    noun = "validation error" if count == 1 else "validation errors"
    lines = [f"{count} {noun} for {err.title}"]
    for item in _validation_errors_without_inputs(err):
        loc = ".".join(str(part) for part in item.get("loc", ())) or "__root__"
        msg = str(item.get("msg", "Input validation failed"))
        error_type = str(item.get("type", "unknown"))
        lines.extend((loc, f"  {msg} [type={error_type}]"))
    return "\n".join(lines)


#: Scheduling flag some MCP clients (notably Gemini CLI batching tool calls)
#: merge into a tool's arguments. Recognized only to *word the rejection
#: helpfully* -- the argument is still rejected, never silently stripped.
_CLIENT_SCHEDULING_FLAG = "wait_for_previous"


def _unexpected_kwargs(error: BaseException) -> list[str]:
    """Argument names rejected as unexpected by schema validation."""
    err = _schema_validation_error(error)
    if err is None:
        return []
    return [
        str(item["loc"][-1])
        for item in err.errors()
        if item.get("type") == "unexpected_keyword_argument" and item.get("loc")
    ]


def _client_label(context: MiddlewareContext | None) -> str | None:
    """``"name version"`` of the connected client, when the handshake exposed it.

    Every hop can be absent (unit-test contexts, background tasks, clients that
    omit ``clientInfo``), so any failure resolves to ``None``. Used only to word
    error suggestions; never gates behavior.
    """
    if context is None:
        return None
    try:
        fastmcp_ctx = context.fastmcp_context
        if fastmcp_ctx is None:
            return None
        params = fastmcp_ctx.session.client_params
        if params is None:
            return None
        info = params.clientInfo
        return f"{info.name} {info.version}".strip()
    except (AttributeError, RuntimeError):
        return None


def _error_tool_result(
    error: Exception,
    context: MiddlewareContext | None = None,
) -> ToolResult:
    """Build a rich ``ToolResult(is_error=True)`` from a tool failure.

    The text carries the error message exactly as raised -- no transform-layer
    prefix -- with the recovery ``suggestion`` appended when available. ``meta``
    mirrors the details: ``error_type`` (the ``__cause__`` class when chained, so
    agents see ``PaneNotFound`` not the wrapper), ``expected`` (True for
    agent-correctable failures), and ``suggestion`` (carried by the error or
    synthesized for rejected unexpected arguments). ``structured_content`` is
    left unset so an error-shaped payload never fails a strict client's
    output-schema validation.
    """
    cause = error.__cause__
    origin = cause if cause is not None else error
    meta: dict[str, t.Any] = {
        "error_type": type(origin).__name__,
        "expected": isinstance(error, ExpectedToolError)
        or _is_schema_validation_error(error),
    }
    text = (
        _format_schema_validation_error(error)
        if _is_schema_validation_error(error)
        else str(error)
    )
    suggestion = getattr(error, "suggestion", None)
    if suggestion is None:
        unknown = _unexpected_kwargs(error)
        if unknown:
            suggestion = (
                f"Remove or correct the unrecognized argument(s): {', '.join(unknown)}."
            )
            if _CLIENT_SCHEDULING_FLAG in unknown:
                client = _client_label(context)
                who = (
                    f"your client ({client})"
                    if client
                    else "some clients (e.g. Gemini CLI)"
                )
                suggestion += (
                    f" {_CLIENT_SCHEDULING_FLAG} is a scheduling flag {who} can "
                    f"leak into batched tool calls; retry the call without it."
                )
    if suggestion:
        meta["suggestion"] = suggestion
        text = f"{text}\n{suggestion}"
    return ToolResult(
        content=[TextContent(type="text", text=text)],
        meta=meta,
        is_error=True,
    )


class ToolErrorResultMiddleware(ErrorHandlingMiddleware):
    """Convert tool-call failures into rich ``ToolResult`` errors.

    Replaces the stock ``transform_errors`` ``-32603`` catch-all (which mangled
    every expected failure message into ``"Internal error: ..."``) for
    ``tools/call`` only; non-tool messages fall through to the inherited
    ``on_message`` (preserving the MCP ``-32002`` resource-not-found transform).

    Ordering invariant: must sit **outside** ``AuditMiddleware``,
    ``ReadonlyRetryMiddleware``, and ``SafetyMiddleware`` -- all three depend on
    the failure still being an exception, so converting it to a result deeper in
    the stack would silently break them.
    """

    def _log_error(self, error: Exception, context: MiddlewareContext) -> None:
        """Log at the error's own ``log_level`` instead of a flat ERROR.

        Expected failures (``ExpectedToolError``, argument-schema validation) log
        at WARNING; everything else at ERROR.
        """
        level: int | None = getattr(error, "log_level", None)
        if level is None:
            level = (
                logging.WARNING if _is_schema_validation_error(error) else logging.ERROR
            )

        error_type = type(error).__name__
        method = context.method or "unknown"

        error_key = f"{error_type}:{method}"
        self.error_counts[error_key] = self.error_counts.get(error_key, 0) + 1

        error_text = (
            _format_schema_validation_error(error)
            if _is_schema_validation_error(error)
            else str(error)
        )
        self.logger.log(
            level,
            "Error in %s: %s: %s",
            method,
            error_type,
            error_text,
            exc_info=self.include_traceback,
        )

        if self.error_callback:
            try:
                self.error_callback(error, context)
            except Exception:
                self.logger.exception("Error in error callback")

    async def on_call_tool(
        self,
        context: MiddlewareContext,
        call_next: t.Any,
    ) -> t.Any:
        """Convert tool-call exceptions into ``is_error`` results."""
        try:
            return await call_next(context)
        except Exception as error:
            self._log_error(error, context)
            return _error_tool_result(error, context)


# ---------------------------------------------------------------------------
# Tail-preserving response limiter
# ---------------------------------------------------------------------------

#: Header prefixed to a truncated response.
_TRUNCATION_HEADER_TEMPLATE = "[... truncated {dropped} bytes ...]\n"


class TailPreservingResponseLimitingMiddleware(ResponseLimitingMiddleware):
    """Response-limiter that keeps the tail of oversized output.

    fastmcp's stock :class:`ResponseLimitingMiddleware` keeps the *head*; that is
    exactly wrong for terminal scrollback, where the active prompt and most
    recent output live at the **bottom**. This subclass keeps the tail and
    prefixes a single truncation-header line. Error results keep their
    ``is_error`` flag through truncation (the base path drops it).
    """

    async def on_call_tool(
        self,
        context: MiddlewareContext,
        call_next: t.Any,
    ) -> t.Any:
        """Apply the size cap without dropping ``is_error``."""
        inner: t.Any = None

        async def _capture(
            context: MiddlewareContext[CallToolRequestParams],
        ) -> ToolResult:
            # ``context`` (not ``ctx``): fastmcp's CallNext protocol matches the
            # parameter *name*, not just the shape -- renaming breaks dispatch.
            nonlocal inner
            inner = await call_next(context)
            return t.cast("ToolResult", inner)

        result = await super().on_call_tool(context, _capture)
        if result is not inner and isinstance(inner, ToolResult) and inner.is_error:
            return ToolResult(
                content=result.content,
                meta=result.meta,
                is_error=True,
            )
        return result

    def _truncate_to_result(
        self,
        text: str,
        meta: dict[str, t.Any] | None = None,
    ) -> ToolResult:
        """Keep the last ``max_size`` bytes of ``text`` and prefix a header."""
        encoded = text.encode("utf-8")
        if len(encoded) <= self.max_size:
            return ToolResult(
                content=[TextContent(type="text", text=text)],
                meta=meta if meta is not None else {},
            )

        header = _TRUNCATION_HEADER_TEMPLATE.format(dropped=len(encoded))
        header_bytes = len(header.encode("utf-8"))
        overhead = 50  # JSON-wrapper accounting, mirrors the base class
        target_size = self.max_size - header_bytes - overhead
        if target_size <= 0:
            return ToolResult(
                content=[TextContent(type="text", text=header.rstrip("\n"))],
                meta=meta if meta is not None else {},
            )

        # errors="ignore" so a split UTF-8 sequence at the boundary is dropped
        # rather than corrupting the output.
        tail = encoded[-target_size:].decode("utf-8", errors="ignore")
        dropped = len(encoded) - len(tail.encode("utf-8"))
        final_header = _TRUNCATION_HEADER_TEMPLATE.format(dropped=dropped)
        truncated = final_header + tail
        return ToolResult(
            content=[TextContent(type="text", text=truncated)],
            meta=meta if meta is not None else {},
        )


# ---------------------------------------------------------------------------
# Safety tier gate (runtime)
# ---------------------------------------------------------------------------


class SafetyMiddleware(Middleware):
    """Gate tools by safety tier at runtime (defense in depth).

    The adapter hides over-tier tools from listings statically; this middleware
    blocks *execution* of anything that slips through (e.g. a per-op tool exposed
    via ``expose_operations=True``). Fail-closed: a tool with no recognized tier
    tag is denied.

    Parameters
    ----------
    max_tier : str
        Maximum allowed tier (one of the ``TAG_*`` values in :mod:`._safety`).
    """

    def __init__(self, max_tier: str) -> None:
        self.max_level = _TIER_LEVELS.get(max_tier, 0)

    def _is_allowed(self, tags: set[str]) -> bool:
        """Whether the tool's tags fall within the allowed tier (fail-closed)."""
        found_tier = False
        for tier, level in _TIER_LEVELS.items():
            if tier in tags:
                found_tier = True
                if level > self.max_level:
                    return False
        return found_tier

    async def on_list_tools(
        self,
        context: MiddlewareContext,
        call_next: t.Any,
    ) -> t.Any:
        """Filter tools above the safety tier from the listing."""
        tools = await call_next(context)
        return [tool for tool in tools if self._is_allowed(tool.tags)]

    async def on_call_tool(
        self,
        context: MiddlewareContext,
        call_next: t.Any,
    ) -> t.Any:
        """Block execution of tools above the safety tier."""
        if context.fastmcp_context:
            tool = await context.fastmcp_context.fastmcp.get_tool(context.message.name)
            if tool and not self._is_allowed(tool.tags):
                msg = (
                    f"Tool '{context.message.name}' is not available at the current "
                    f"safety level. Set LIBTMUX_SAFETY=destructive to enable "
                    f"destructive tools."
                )
                raise ExpectedToolError(msg)
        return await call_next(context)


# ---------------------------------------------------------------------------
# Audit middleware
# ---------------------------------------------------------------------------

#: Argument names that carry user payloads we never want in logs (commands,
#: secrets, arbitrary large strings). Matched by exact name, case-sensitive.
#: ``environment`` is dict-shaped: its values are digested while its keys (env
#: var names) stay visible.
_SENSITIVE_ARG_NAMES: frozenset[str] = frozenset(
    {"keys", "text", "command", "value", "content", "shell", "environment"},
)

#: Nested argument containers that may contain sensitive argument names.
_NESTED_ARG_LIST_NAMES: frozenset[str] = frozenset({"operations"})

_NONE_TYPE = type(None)

_SEND_KEYS_OPERATION_ARG_TYPES: dict[str, tuple[type[t.Any], ...]] = {
    "keys": (str,),
    "pane_id": (str, _NONE_TYPE),
    "session_name": (str, _NONE_TYPE),
    "session_id": (str, _NONE_TYPE),
    "window_id": (str, _NONE_TYPE),
    "enter": (bool,),
    "literal": (bool,),
    "suppress_history": (bool,),
}

#: Non-sensitive strings longer than this get truncated in the log summary.
_MAX_LOGGED_STR_LEN: int = 200


def _redact_digest(value: str) -> dict[str, t.Any]:
    """Return a length + SHA-256 prefix summary of ``value``.

    Stable and deterministic, so operators correlate the same payload across log
    lines without ever recording the payload itself.

    Examples
    --------
    >>> _redact_digest("hello")
    {'len': 5, 'sha256_prefix': '2cf24dba5fb0'}
    >>> _redact_digest("")
    {'len': 0, 'sha256_prefix': 'e3b0c44298fc'}
    """
    return {
        "len": len(value),
        "sha256_prefix": hashlib.sha256(value.encode("utf-8")).hexdigest()[:12],
    }


def _redacted_value_shape(value: t.Any) -> dict[str, t.Any]:
    """Return non-payload metadata for a value that cannot be logged."""
    return {"type": type(value).__name__, "redacted": True}


def _summarize_send_keys_operation_args(args: dict[str, t.Any]) -> dict[str, t.Any]:
    """Summarize one send-keys batch operation for audit logging."""
    summary: dict[str, t.Any] = {}
    for key, value in args.items():
        expected_types = _SEND_KEYS_OPERATION_ARG_TYPES.get(key)
        if expected_types is None or not isinstance(value, expected_types):
            summary[key] = _redacted_value_shape(value)
        else:
            summary[key] = _summarize_args({key: value})[key]
    return summary


def _summarize_tool_batch_operation_args(args: dict[str, t.Any]) -> dict[str, t.Any]:
    """Summarize one generic tool-batch operation for audit logging."""
    summary: dict[str, t.Any] = {}
    for key, value in args.items():
        if key == "tool" and isinstance(value, str):
            summary[key] = value
        elif key == "arguments" and isinstance(value, dict):
            summary[key] = _summarize_args(value)
        else:
            summary[key] = _redacted_value_shape(value)
    return summary


def _summarize_nested_operation_args(args: dict[str, t.Any]) -> dict[str, t.Any]:
    """Summarize a known nested operation shape."""
    if "tool" in args or "arguments" in args:
        return _summarize_tool_batch_operation_args(args)
    return _summarize_send_keys_operation_args(args)


def _summarize_args(args: dict[str, t.Any]) -> dict[str, t.Any]:
    """Summarize tool arguments for audit logging.

    Sensitive keys are replaced by a digest; over-long strings truncated;
    everything else passes through. Dict-shaped sensitive values keep their keys
    but digest each value; known nested operation lists are summarized
    recursively.

    Examples
    --------
    >>> _summarize_args({"pane_id": "%1", "bracket": True})
    {'pane_id': '%1', 'bracket': True}
    >>> _summarize_args({"keys": "rm -rf /"})["keys"]["len"]
    8
    >>> redacted = _summarize_args({"environment": {"FOO": "bar"}})
    >>> redacted["environment"]["FOO"]["len"]
    3
    >>> "bar" in str(redacted)
    False
    """
    summary: dict[str, t.Any] = {}
    for key, value in args.items():
        if key in _SENSITIVE_ARG_NAMES and isinstance(value, str):
            summary[key] = _redact_digest(value)
        elif key in _SENSITIVE_ARG_NAMES and isinstance(value, dict):
            summary[key] = {k: _redact_digest(str(v)) for k, v in value.items()}
        elif key in _NESTED_ARG_LIST_NAMES:
            if isinstance(value, list):
                summary[key] = [
                    _summarize_nested_operation_args(item)
                    if isinstance(item, dict)
                    else _redacted_value_shape(item)
                    for item in value
                ]
            else:
                summary[key] = _redacted_value_shape(value)
        elif isinstance(value, str) and len(value) > _MAX_LOGGED_STR_LEN:
            summary[key] = value[:_MAX_LOGGED_STR_LEN] + "...<truncated>"
        else:
            summary[key] = value
    return summary


class AuditMiddleware(Middleware):
    """Emit a structured log record per tool invocation.

    One ``INFO`` record per call carries the tool name, outcome, duration, error
    type on failure, the fastmcp client/request ids when available, and a
    redacted argument summary -- all in the record's ``extra`` (the message is a
    static template, per the project logging standard), so payload-bearing
    arguments never reach the log as raw text.

    Parameters
    ----------
    logger_name : str
        Name of the :mod:`logging` logger used for audit records.
    """

    def __init__(
        self,
        logger_name: str = "libtmux.experimental.mcp.audit",
    ) -> None:
        self._logger = logging.getLogger(logger_name)

    async def on_call_tool(
        self,
        context: MiddlewareContext,
        call_next: t.Any,
    ) -> t.Any:
        """Wrap the tool call with a timer and emit one audit record."""
        start = time.monotonic()
        tool_name = getattr(context.message, "name", "<unknown>")
        raw_args = getattr(context.message, "arguments", None) or {}
        args_summary = _summarize_args(raw_args)

        client_id: str | None = None
        request_id: str | None = None
        if context.fastmcp_context is not None:
            client_id = getattr(context.fastmcp_context, "client_id", None)
            request_id = getattr(context.fastmcp_context, "request_id", None)

        try:
            result = await call_next(context)
        except Exception as exc:
            self._logger.info(
                "tool call failed",
                extra={
                    "tmux_subcommand": tool_name,
                    "outcome": "error",
                    "error_type": type(exc).__name__,
                    "duration_ms": round((time.monotonic() - start) * 1000.0, 2),
                    "client_id": client_id,
                    "request_id": request_id,
                    "tmux_args": args_summary,
                },
            )
            raise

        self._logger.info(
            "tool call completed",
            extra={
                "tmux_subcommand": tool_name,
                "outcome": "ok",
                "duration_ms": round((time.monotonic() - start) * 1000.0, 2),
                "client_id": client_id,
                "request_id": request_id,
                "tmux_args": args_summary,
            },
        )
        return result


# ---------------------------------------------------------------------------
# Readonly retry
# ---------------------------------------------------------------------------


class ReadonlyRetryMiddleware(Middleware):
    """Retry transient libtmux failures, but only for readonly tools.

    Composes fastmcp's :class:`RetryMiddleware`. Mutating and destructive tools
    pass straight through -- re-running them on a transient socket error would
    silently double side effects. Readonly tools are safe to retry. The default
    trigger is :class:`libtmux.exc.LibTmuxException` (libtmux wraps the transient
    subprocess failures); fastmcp's stock ``(ConnectionError, TimeoutError)`` does
    not match these, so the upstream default would be a silent no-op.

    Place this **inside** ``AuditMiddleware`` (so retried calls are audited once)
    and **outside** ``SafetyMiddleware`` (so tier-denied tools never reach retry).
    """

    def __init__(
        self,
        max_retries: int = 1,
        base_delay: float = 0.1,
        max_delay: float = 1.0,
        backoff_multiplier: float = 2.0,
        retry_exceptions: tuple[type[Exception], ...] = (libtmux_exc.LibTmuxException,),
        logger_: logging.Logger | None = None,
    ) -> None:
        if logger_ is None:
            logger_ = logging.getLogger("libtmux.experimental.mcp.retry")
        self._retry = RetryMiddleware(
            max_retries=max_retries,
            base_delay=base_delay,
            max_delay=max_delay,
            backoff_multiplier=backoff_multiplier,
            retry_exceptions=retry_exceptions,
            logger=logger_,
        )

    async def on_call_tool(
        self,
        context: MiddlewareContext,
        call_next: t.Any,
    ) -> t.Any:
        """Delegate to the upstream retry only for tools tagged readonly."""
        if context.fastmcp_context:
            tool = await context.fastmcp_context.fastmcp.get_tool(context.message.name)
            if tool and TAG_READONLY in tool.tags:
                return await self._retry.on_request(context, call_next)
        return await call_next(context)
