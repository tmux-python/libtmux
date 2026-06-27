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

import logging
import typing as t

from fastmcp.server.middleware import MiddlewareContext
from fastmcp.server.middleware.error_handling import ErrorHandlingMiddleware
from fastmcp.server.middleware.response_limiting import ResponseLimitingMiddleware
from fastmcp.tools.base import ToolResult
from mcp.types import CallToolRequestParams, TextContent
from pydantic import ValidationError as PydanticValidationError

from libtmux.experimental.mcp._safety import ExpectedToolError

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
