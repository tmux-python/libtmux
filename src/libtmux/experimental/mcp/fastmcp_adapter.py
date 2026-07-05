"""Optional fastmcp adapter -- expose the typed projection on a FastMCP server.

This is the thin, framework-specific edge. It requires the ``mcp`` extra
(``pip install libtmux[mcp]``); fastmcp is imported lazily so the rest of
:mod:`libtmux.experimental.mcp` stays dependency-free.

The vocabulary is **async-first**: :func:`build_async_server` registers the
``async def`` tools so FastMCP awaits them directly on its event loop (the right
fit for the persistent control-mode connection's loop affinity), and adds the
live event stream. :func:`build_server` is the synchronous wrapper -- it
registers the derived sync twins, which FastMCP offloads to a worker thread.

Both project the same three tool layers over one engine:

1. **Curated vocabulary** -- the intuitive, hand-written tools
   (:mod:`~libtmux.experimental.mcp.vocabulary`), always visible.
2. **Per-operation tools** -- one ``op_<kind>`` per registered operation, hidden
   behind the ``per-op`` tag by default (the full surface is large).
3. **Plan tools** -- compose and run a whole :class:`~..ops.plan.LazyPlan`.
"""

from __future__ import annotations

import dataclasses
import inspect
import os
import typing as t

from libtmux.experimental.mcp import vocabulary
from libtmux.experimental.mcp.registry import OperationToolRegistry
from libtmux.experimental.mcp.vocabulary._caller import CallerContext

if t.TYPE_CHECKING:
    from collections.abc import Callable

    from fastmcp import FastMCP

    from libtmux.experimental.engines.base import AsyncTmuxEngine, TmuxEngine
    from libtmux.experimental.mcp.descriptor import ToolDescriptor
    from libtmux.experimental.mcp.events import EventMode, EventSource

# (public tool name, safety tier). The async tool is ``a<name>`` and the sync
# twin is ``<name>`` -- a single table drives both surfaces.
_TOOLS: tuple[tuple[str, str], ...] = (
    ("create_session", "mutating"),
    ("create_window", "mutating"),
    ("split_pane", "mutating"),
    ("new_pane", "mutating"),
    ("send_input", "mutating"),
    ("capture_pane", "readonly"),
    ("capture_active_pane", "readonly"),
    ("grep_pane", "readonly"),
    ("list_sessions", "readonly"),
    ("list_windows", "readonly"),
    ("list_panes", "readonly"),
    ("list_clients", "readonly"),
    ("has_session", "readonly"),
    ("show_options", "readonly"),
    ("show_buffer", "readonly"),
    ("display_message", "readonly"),
    ("resolve_relative_pane", "readonly"),
    ("capture_relative_pane", "readonly"),
    ("grep_relative_pane", "readonly"),
    ("search_panes", "readonly"),
    ("find_pane_by_position", "readonly"),
    ("rename_window", "mutating"),
    ("rename_session", "mutating"),
    ("select_window", "mutating"),
    ("select_layout", "mutating"),
    ("select_pane", "mutating"),
    ("move_window", "mutating"),
    ("swap_window", "mutating"),
    ("resize_pane", "mutating"),
    ("swap_pane", "mutating"),
    ("join_pane", "mutating"),
    ("break_pane", "mutating"),
    ("respawn_pane", "mutating"),
    ("set_option", "mutating"),
    ("set_buffer", "mutating"),
    ("paste_buffer", "mutating"),
    ("run_tmux", "mutating"),
    ("kill_pane", "destructive"),
    ("kill_window", "destructive"),
    ("kill_session", "destructive"),
)

# Read-only discovery anchors -- the tools an agent should reach for first.
# Tagged with vendor metadata best-effort (fastmcp 3.4.2 passes ``_meta`` through
# but assigns it no semantics, so this is advisory only).
_ANCHORS = frozenset(
    {
        "list_panes",
        "search_panes",
        "grep_relative_pane",
        "capture_active_pane",
        "get_caller_context",
    },
)

# Fail loud at import if an anchor name drifts from the registered tool set
# (the alwaysLoad metadata is opaque, so a typo would otherwise fail silently).
_unknown_anchors = _ANCHORS - ({name for name, _ in _TOOLS} | {"get_caller_context"})
if _unknown_anchors:  # pragma: no cover - import-time guard
    _msg = f"unknown anchor tools: {sorted(_unknown_anchors)}"
    raise RuntimeError(_msg)

_TARGET_HELP = (
    "tmux target: an id (%pane, @window, $session), a name, or 'session:window.pane'"
)


def _agent_context_segment(ctx: CallerContext) -> str:
    """Return the agent-context paragraph naming the caller's pane."""
    if ctx.in_tmux and ctx.pane_id:
        socket = ctx.socket_path or "default"
        session = f" (session {ctx.session_id})" if ctx.session_id else ""
        return (
            f"Agent context: this MCP runs from pane {ctx.pane_id} on socket "
            f'{socket}{session}. That pane is flagged is_caller ("1" in '
            "list_panes rows, true in search_panes matches) -- call "
            "get_caller_context to read it. "
            "Omitting a target/origin on the caller-aware tools "
            "(resolve_relative_pane/capture_relative_pane/grep_relative_pane) "
            "means YOUR pane."
        )
    return (
        "Agent context: this MCP is not running inside a tmux pane, so there is no "
        "caller pane and no row is flagged is_caller; the relative tools "
        "(resolve_relative_pane/capture_relative_pane/grep_relative_pane) require an "
        "explicit origin pane id here."
    )


def _instructions(ctx: CallerContext, *, events_enabled: bool = False) -> str:
    """Compose the server instructions, woven with the live caller context.

    *events_enabled* gates the live-output guidance (``wait_for_output`` /
    ``watch_events``), which is registered only on a streaming control-mode
    server -- the sync server omits it so it never names a tool it lacks.
    """
    closer = (
        "The curated tools cover most needs; the per-operation surface (op_*) "
        "and the plan tools (preview_plan/execute_plan/result_schema/"
        "build_workspace) are power-use."
    )
    if events_enabled:
        closer += (
            " For live output: wait_for_output waits for one pane to settle "
            "(run-a-command-and-wait); watch_events/poll_events stream/buffer raw "
            "control-mode notifications across the server."
        )
    segments = [
        "This MCP drives a real tmux server through typed tools: sessions, "
        "windows, panes, terminal scrollback, send-keys, copy-mode buffers. "
        "Targets accept tmux ids (%pane, @window, $session), names, or "
        "'session:window.pane'.",
        "When to invoke: managing tmux panes/windows/sessions; reading "
        "terminal scrollback (capture_pane/grep_pane/search_panes); sending "
        "keystrokes to a running shell or REPL (send_input); copy-mode and "
        "paste-buffer work; operating on a pane relative to another or to you "
        "(capture_relative_pane/grep_relative_pane).",
        "Do NOT invoke for: editor panes you edit via file tools; browser tabs "
        "or web content; GUI application windows; notebook cells; any non-tmux "
        "terminal surface. tmux only sees terminal panes -- it cannot read a "
        "browser or GUI app.",
        "Prefer a concrete %N pane id; resolve relative or caller-relative "
        "targets to a concrete %N before capture/send. Never hand a directional "
        "special target ({up-of}/{down-of}/{left-of}/{right-of}) to "
        "capture_pane/grep_pane/send_input -- those resolve against THIS MCP's "
        "control client, not your pane; use capture_relative_pane / "
        "grep_relative_pane / resolve_relative_pane instead.",
        _agent_context_segment(ctx),
    ]
    if events_enabled:
        segments.append(
            "Run a command and wait for it to finish / for completion "
            "(long-running builds, test runs like `uv run pytest`, installs, a "
            "server reaching ready): split_pane or pick a pane, send_input the "
            "command (enter=True), then call wait_for_output on that same pane -- "
            "it folds the live output and returns when the pane goes quiet "
            "(settles), needle-free (no regex, no sentinel). Prefer this over "
            "polling with sleep + capture_pane: wait_for_output is event-backed, "
            "returns the captured_text, and reports done.pane_dead / "
            "done.pane_dead_status (process exit / return code) plus "
            "done.pane_current_command so you can tell finished from "
            "blocked-on-input. Settled means output stopped, not that the command "
            "succeeded or failed -- read the done metadata to confirm exit status.",
        )
    segments.append(
        "list_panes/list_windows/show_options query tmux metadata (format "
        "fields); grep_pane (one pane) and search_panes (across panes) search "
        "terminal text (scrollback). Pick the right one for 'which pane shows X'.",
    )
    segments.append(closer)
    return "\n\n".join(segments)


def _summary(doc: str | None) -> str | None:
    """Return the first non-empty docstring line."""
    for line in (doc or "").splitlines():
        if line.strip():
            return line.strip()
    return None


def _bind_engine(
    fn: Callable[..., t.Any],
    engine: TmuxEngine | AsyncTmuxEngine,
    *,
    is_async: bool,
) -> Callable[..., t.Any]:
    """Bind *engine* out of *fn*, returning a wrapper fastmcp can introspect.

    Carries *pre-resolved* annotations (with ``engine`` removed) and an explicit
    ``__signature__`` so fastmcp's ``get_type_hints`` never re-evaluates the
    forward references against the wrong module globals. The async branch returns
    a coroutine function so FastMCP awaits it on the loop; the sync branch a plain
    function (offloaded to a thread).
    """
    hints = t.get_type_hints(fn)
    signature = inspect.signature(fn)
    params = [p for name, p in signature.parameters.items() if name != "engine"]

    async def _async_tool(*args: t.Any, **kwargs: t.Any) -> t.Any:
        return await fn(engine, *args, **kwargs)

    def _sync_tool(*args: t.Any, **kwargs: t.Any) -> t.Any:
        return fn(engine, *args, **kwargs)

    # Typed Any so the dunder rebinds below are not checked against a plain
    # Callable (which carries no __name__/__signature__ in mypy's view).
    tool: t.Any = _async_tool if is_async else _sync_tool
    tool.__name__ = fn.__name__
    tool.__qualname__ = fn.__name__
    tool.__doc__ = fn.__doc__
    tool.__signature__ = signature.replace(parameters=params)
    tool.__annotations__ = {k: v for k, v in hints.items() if k != "engine"}
    return t.cast("Callable[..., t.Any]", tool)


def register_vocabulary(
    mcp: FastMCP,
    engine: TmuxEngine | AsyncTmuxEngine,
    *,
    is_async: bool,
) -> None:
    """Register the curated vocabulary as tools on *mcp*, bound to *engine*."""
    from fastmcp.tools import FunctionTool
    from mcp.types import ToolAnnotations

    for name, safety in _TOOLS:
        fn = getattr(vocabulary, ("a" + name) if is_async else name)
        annotations = ToolAnnotations(
            title=name,
            readOnlyHint=safety == "readonly",
            destructiveHint=safety == "destructive",
        )
        tool = FunctionTool.from_function(
            _bind_engine(fn, engine, is_async=is_async),
            name=name,
            description=_summary(fn.__doc__),
            tags={safety},
            annotations=annotations,
            meta={"anthropic/alwaysLoad": True} if name in _ANCHORS else None,
        )
        mcp.add_tool(tool)


def register_caller_context(mcp: FastMCP, ctx: CallerContext) -> None:
    """Register the ``get_caller_context`` anchor returning the build-time context.

    It closes over the context read once from the server's environment -- it must
    *not* re-query tmux, which would answer for the control client, not the
    caller.
    """
    from fastmcp.tools import FunctionTool
    from mcp.types import ToolAnnotations

    def get_caller_context() -> CallerContext:
        """Return the tmux pane/server discovered for this MCP.

        From the server's own env, an explicit override, or a bounded ``/proc``
        parent walk -- inspect the ``source`` field for which.
        """
        return ctx

    tool = FunctionTool.from_function(
        get_caller_context,
        name="get_caller_context",
        description=_summary(get_caller_context.__doc__),
        tags={"readonly"},
        annotations=ToolAnnotations(title="get_caller_context", readOnlyHint=True),
        meta=(
            {"anthropic/alwaysLoad": True} if "get_caller_context" in _ANCHORS else None
        ),
    )
    mcp.add_tool(tool)


def _op_input_schema(descriptor: ToolDescriptor) -> dict[str, t.Any]:
    """Return the per-op tool's input schema, re-adding the target params.

    The :class:`~..registry.OperationToolRegistry` omits ``target`` /
    ``src_target`` from a descriptor's params (they are polymorphic
    :data:`~..ops._types.Target` values), so the schema is re-completed here --
    at the framework edge -- as plain ``string`` params.
    """
    schema = descriptor.input_schema()
    fields = {
        field.name: field for field in dataclasses.fields(descriptor.operation_cls)
    }
    target_props: dict[str, t.Any] = {}
    required = list(schema.get("required", []))
    for name in ("target", "src_target"):
        field = fields.get(name)
        if field is None:
            continue
        target_props[name] = {"type": "string", "description": _TARGET_HELP}
        is_required = (
            field.default is dataclasses.MISSING
            and field.default_factory is dataclasses.MISSING
        )
        if is_required and name not in required:
            required.append(name)
    if target_props:
        schema["properties"] = {**target_props, **schema["properties"]}
    if required:
        schema["required"] = required
    return schema


def register_operations(
    mcp: FastMCP,
    engine: TmuxEngine | AsyncTmuxEngine,
    *,
    is_async: bool,
    registry: OperationToolRegistry | None = None,
    hidden: bool = True,
) -> None:
    """Register one ``op_<kind>`` tool per registered operation.

    Each tool carries the operation's precomputed JSON schema and dispatches to
    :meth:`~..descriptor.ToolDescriptor.build` + :func:`~..ops.execute.run` (or
    :func:`~..ops.execute.arun` for an async engine), returning the serialized
    result. Tools are tagged ``per-op`` plus their safety tier; when *hidden*
    (the default) the ``per-op`` tag is disabled.
    """
    from fastmcp.tools import Tool, ToolResult
    from mcp.types import ToolAnnotations
    from pydantic import PrivateAttr

    from libtmux.experimental.mcp.vocabulary._bridge import SyncToAsyncEngine
    from libtmux.experimental.mcp.vocabulary._resolve import guard_destructive_op
    from libtmux.experimental.ops import arun as arun_op, run as run_op
    from libtmux.experimental.ops.serialize import result_to_dict

    class _OperationTool(Tool):
        """A per-operation tool: explicit schema + dispatch to the registry."""

        _descriptor: t.Any = PrivateAttr(default=None)
        _engine: t.Any = PrivateAttr(default=None)
        _is_async: bool = PrivateAttr(default=False)

        async def run(self, arguments: dict[str, t.Any]) -> ToolResult:
            operation = self._descriptor.build(**arguments)
            # The per-op surface dispatches around the curated guard, so apply the
            # self-kill guard here too (a sync engine is wrapped to async for it).
            guard_engine = (
                self._engine if self._is_async else SyncToAsyncEngine(self._engine)
            )
            await guard_destructive_op(guard_engine, operation)
            if self._is_async:
                result = await arun_op(operation, self._engine)
            else:
                result = run_op(operation, self._engine)
            return ToolResult(
                structured_content=result_to_dict(result),
                is_error=not result.ok,
            )

    reg = registry if registry is not None else OperationToolRegistry()
    for descriptor in reg.descriptors():
        annotations = ToolAnnotations(
            title=descriptor.title,
            readOnlyHint=descriptor.safety == "readonly",
            destructiveHint=descriptor.safety == "destructive",
        )
        tool = _OperationTool(
            name=f"op_{descriptor.name}",
            description=descriptor.description or None,
            parameters=_op_input_schema(descriptor),
            tags={*descriptor.tags, "per-op"},
            annotations=annotations,
        )
        tool._descriptor = descriptor
        tool._engine = engine
        tool._is_async = is_async
        mcp.add_tool(tool)
    if hidden:
        mcp.disable(tags={"per-op"})


def register_plan_tools(
    mcp: FastMCP,
    engine: TmuxEngine | AsyncTmuxEngine,
    *,
    is_async: bool,
    registry: OperationToolRegistry | None = None,
) -> None:
    """Register the plan-tier tools (compose + run serialized :class:`LazyPlan`s).

    ``preview_plan`` / ``result_schema`` are pure; ``execute_plan`` runs a
    serialized plan (via :func:`~..mcp.plan_tools.aexecute_plan` on an async
    engine). ``build_workspace`` is registered only on the synchronous server
    (the declarative runner is synchronous).
    """
    from fastmcp.tools import FunctionTool
    from mcp.types import ToolAnnotations

    from libtmux.experimental.mcp import plan_tools as _plan
    from libtmux.experimental.ops import LazyPlan
    from libtmux.experimental.ops.planner import (
        FoldingPlanner,
        MarkedPlanner,
        Planner,
        SequentialPlanner,
    )

    reg = registry if registry is not None else OperationToolRegistry()
    planners: dict[str, type[Planner]] = {
        "sequential": SequentialPlanner,
        "folding": FoldingPlanner,
        "marked": MarkedPlanner,
    }

    def _plan_from_dicts(operations: list[dict[str, t.Any]]) -> LazyPlan:
        # from_list (not add) so a serialized find-or-create `ensure` probe
        # survives the round-trip instead of being silently dropped.
        return LazyPlan.from_list(operations)

    def _planner(name: str) -> Planner:
        chosen = planners.get(name)
        if chosen is None:
            msg = f"unknown planner {name!r}; choose from {sorted(planners)}"
            raise ValueError(msg)
        return chosen()

    def preview_plan(
        operations: list[dict[str, t.Any]],
        version: str | None = None,
    ) -> dict[str, t.Any]:
        """Render a serialized plan without executing it (refs render as null)."""
        preview = _plan.preview_plan(_plan_from_dicts(operations), version=version)
        return {
            "ok": preview.ok,
            "operations": preview.operations,
            "argv": [list(item) if item is not None else None for item in preview.argv],
        }

    def explain_plan(
        operations: list[dict[str, t.Any]],
        planner: str = "marked",
    ) -> dict[str, t.Any]:
        """Explain why *planner* folds or breaks a serialized plan (pure)."""
        explanation = _plan.explain_plan(
            _plan_from_dicts(operations),
            planner=_planner(planner),
        )
        return {"steps": explanation.steps}

    def result_schema(kind: str) -> dict[str, t.Any]:
        """Report what an operation kind returns, for planning forward refs."""
        schema = _plan.result_schema(reg, kind)
        return {
            "kind": schema.kind,
            "result_type": schema.result_type,
            "schema": schema.schema,
            "binding_fields": schema.binding_fields,
        }

    tools: list[tuple[Callable[..., t.Any], str]] = [
        (preview_plan, "readonly"),
        (explain_plan, "readonly"),
        (result_schema, "readonly"),
    ]

    if is_async:

        async def execute_plan(
            operations: list[dict[str, t.Any]],
            planner: str = "sequential",
            version: str | None = None,
        ) -> dict[str, t.Any]:
            """Execute a serialized plan over the engine; return results + bindings."""
            outcome = await _plan.aexecute_plan(
                _plan_from_dicts(operations),
                t.cast("AsyncTmuxEngine", engine),
                version=version,
                planner=_planner(planner),
            )
            return {
                "ok": outcome.ok,
                "results": outcome.results,
                "bindings": outcome.bindings,
            }

        async def build_workspace(
            spec: dict[str, t.Any],
            preflight: bool = True,
            version: str | None = None,
        ) -> dict[str, t.Any]:
            """Build a declarative workspace (the Declarative tier) in one call."""
            outcome = await _plan.abuild_workspace(
                spec,
                t.cast("AsyncTmuxEngine", engine),
                version=version,
                preflight=preflight,
            )
            return {
                "ok": outcome.ok,
                "results": outcome.results,
                "bindings": outcome.bindings,
            }

        tools.append((execute_plan, "mutating"))
        tools.append((build_workspace, "mutating"))
    else:

        def execute_plan(  # type: ignore[misc]
            operations: list[dict[str, t.Any]],
            planner: str = "sequential",
            version: str | None = None,
        ) -> dict[str, t.Any]:
            """Execute a serialized plan over the engine; return results + bindings."""
            outcome = _plan.execute_plan(
                _plan_from_dicts(operations),
                t.cast("TmuxEngine", engine),
                version=version,
                planner=_planner(planner),
            )
            return {
                "ok": outcome.ok,
                "results": outcome.results,
                "bindings": outcome.bindings,
            }

        def build_workspace(  # type: ignore[misc]
            spec: dict[str, t.Any],
            preflight: bool = True,
            version: str | None = None,
        ) -> dict[str, t.Any]:
            """Build a declarative workspace (the Declarative tier) in one call."""
            outcome = _plan.build_workspace(
                spec,
                t.cast("TmuxEngine", engine),
                version=version,
                preflight=preflight,
            )
            return {
                "ok": outcome.ok,
                "results": outcome.results,
                "bindings": outcome.bindings,
            }

        tools.append((execute_plan, "mutating"))
        tools.append((build_workspace, "mutating"))

    for fn, safety in tools:
        annotations = ToolAnnotations(
            title=fn.__name__,
            readOnlyHint=safety == "readonly",
            destructiveHint=False,
        )
        tool = FunctionTool.from_function(
            fn,
            name=fn.__name__,
            description=_summary(fn.__doc__),
            tags={"plan", safety},
            annotations=annotations,
        )
        mcp.add_tool(tool)


def _stash_caller(engine: t.Any, ctx: CallerContext) -> None:
    """Stash the discovered caller on the engine so the tool bodies can read it.

    The curated tool bodies bind only ``engine``; stashing the once-discovered
    context here (read by :func:`~.vocabulary._resolve.caller_of`) threads caller
    identity to them without changing every tool signature.
    """
    engine._caller_context = ctx


def _make_middleware(level: str) -> list[t.Any]:
    """Build the middleware stack (outer-to-inner; Safety innermost, fail-closed).

    Timing observes; the tail-preserving limiter caps oversized scrollback;
    ToolErrorResult converts failures to typed error results; Audit records each
    call; ReadonlyRetry retries readonly tools; Safety gates execution by tier.
    """
    from fastmcp.server.middleware.timing import TimingMiddleware

    from libtmux.experimental.mcp.middleware import (
        _RESPONSE_LIMITED_TOOLS,
        DEFAULT_RESPONSE_LIMIT_BYTES,
        AuditMiddleware,
        ReadonlyRetryMiddleware,
        SafetyMiddleware,
        TailPreservingResponseLimitingMiddleware,
        ToolErrorResultMiddleware,
    )

    return [
        TimingMiddleware(),
        TailPreservingResponseLimitingMiddleware(
            max_size=DEFAULT_RESPONSE_LIMIT_BYTES,
            tools=list(_RESPONSE_LIMITED_TOOLS),
        ),
        ToolErrorResultMiddleware(transform_errors=True),
        AuditMiddleware(),
        ReadonlyRetryMiddleware(),
        SafetyMiddleware(max_tier=level),
    ]


def _apply_safety_gate(mcp: FastMCP, max_tier: str) -> None:
    """Hide tools above *max_tier* without re-exposing hidden per-op tools.

    Subtractive (never calls ``enable``): disable only the over-tier tiers, so the
    per-op hide (``mcp.disable(tags={'per-op'})`` in :func:`register_operations`)
    and any individually-disabled tool survive. ``readonly`` is always allowed.
    """
    from libtmux.experimental.mcp._safety import (
        TAG_DESTRUCTIVE,
        TAG_MUTATING,
        TAG_READONLY,
    )

    allowed = {TAG_READONLY}
    if max_tier in {TAG_MUTATING, TAG_DESTRUCTIVE}:
        allowed.add(TAG_MUTATING)
    if max_tier == TAG_DESTRUCTIVE:
        allowed.add(TAG_DESTRUCTIVE)
    for tier in (TAG_MUTATING, TAG_DESTRUCTIVE):
        if tier not in allowed:
            mcp.disable(tags={tier})


def _resolve_level(safety_level: str | None) -> str:
    """Resolve the effective tier from an explicit arg or ``LIBTMUX_SAFETY``."""
    from libtmux.experimental.mcp._safety import resolve_safety_level

    return resolve_safety_level(
        safety_level if safety_level is not None else os.environ.get("LIBTMUX_SAFETY"),
    )


def build_server(
    engine: TmuxEngine,
    *,
    name: str = "tmux",
    instructions: str | None = None,
    include_operations: bool = True,
    expose_operations: bool = False,
    include_plan_tools: bool = True,
    include_middleware: bool = True,
    include_prompts: bool = True,
    include_resources: bool = True,
    safety_level: str | None = None,
    caller: CallerContext | None = None,
) -> FastMCP:
    """Build a synchronous FastMCP server over a sync *engine*.

    The sync wrapper: the curated tools are the derived sync twins, which FastMCP
    offloads to a worker thread. Prefer :func:`build_async_server` for the
    async-first surface and the event stream. *caller* defaults to
    :meth:`CallerContext.discover`.

    *safety_level* (or ``LIBTMUX_SAFETY``) gates the tool surface by tier
    (``readonly``/``mutating``/``destructive``, default ``mutating``); over-tier
    tools are hidden and blocked. *include_middleware* adds the full stack
    (timing, response cap, error results, audit, readonly retry, safety).
    """
    from fastmcp import FastMCP

    level = _resolve_level(safety_level)
    ctx = caller if caller is not None else CallerContext.discover()
    _stash_caller(engine, ctx)
    mcp: FastMCP = FastMCP(
        name=name,
        instructions=instructions or _instructions(ctx),
        middleware=_make_middleware(level) if include_middleware else None,
    )
    registry = OperationToolRegistry()
    register_vocabulary(mcp, engine, is_async=False)
    register_caller_context(mcp, ctx)
    if include_prompts:
        from libtmux.experimental.mcp.prompts import register_prompts

        register_prompts(mcp)
    if include_operations:
        register_operations(
            mcp,
            engine,
            is_async=False,
            registry=registry,
            hidden=not expose_operations,
        )
    if include_plan_tools:
        register_plan_tools(mcp, engine, is_async=False, registry=registry)
    if include_resources:
        from libtmux.experimental.mcp.resources import register_resources

        register_resources(mcp, engine, is_async=False)
    _apply_safety_gate(mcp, level)
    return mcp


def build_async_server(
    engine: AsyncTmuxEngine,
    *,
    name: str = "tmux",
    instructions: str | None = None,
    include_operations: bool = True,
    expose_operations: bool = False,
    include_plan_tools: bool = True,
    include_middleware: bool = True,
    include_prompts: bool = True,
    include_resources: bool = True,
    lifespan: bool = True,
    safety_level: str | None = None,
    events: EventMode = "push",
    event_source: EventSource = "subscription",
    caller: CallerContext | None = None,
) -> FastMCP:
    """Build the async-first FastMCP server over an async *engine*.

    The curated tools and per-op/plan tools are registered as ``async`` and
    awaited directly on FastMCP's event loop. When *engine* supports a
    notification stream (a control-mode engine), the live event tools are
    registered per *events* (``"push"``/``"pull"``/``"both"``/``"off"``).
    *caller* defaults to :meth:`CallerContext.discover`.

    *safety_level* (or ``LIBTMUX_SAFETY``) and *include_middleware* behave as in
    :func:`build_server`.
    """
    from fastmcp import FastMCP

    from libtmux.experimental.mcp._lifespan import make_lifespan
    from libtmux.experimental.mcp.events import _supports_stream, register_events

    level = _resolve_level(safety_level)
    ctx = caller if caller is not None else CallerContext.discover()
    _stash_caller(engine, ctx)
    events_enabled = events != "off" and _supports_stream(engine)
    mcp: FastMCP = FastMCP(
        name=name,
        instructions=instructions or _instructions(ctx, events_enabled=events_enabled),
        middleware=_make_middleware(level) if include_middleware else None,
        lifespan=make_lifespan(engine) if lifespan else None,
    )
    registry = OperationToolRegistry()
    register_vocabulary(mcp, engine, is_async=True)
    register_caller_context(mcp, ctx)
    if include_prompts:
        from libtmux.experimental.mcp.prompts import register_prompts

        register_prompts(mcp, events_enabled=events_enabled)
    if include_operations:
        register_operations(
            mcp,
            engine,
            is_async=True,
            registry=registry,
            hidden=not expose_operations,
        )
    if include_plan_tools:
        register_plan_tools(mcp, engine, is_async=True, registry=registry)
    if include_resources:
        from libtmux.experimental.mcp.resources import register_resources

        register_resources(mcp, engine, is_async=True)
    register_events(mcp, engine, mode=events, source=event_source)
    _apply_safety_gate(mcp, level)
    return mcp
