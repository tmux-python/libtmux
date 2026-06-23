"""Optional fastmcp adapter -- expose the typed projection on a FastMCP server.

This is the thin, framework-specific edge. It requires the ``mcp`` extra
(``pip install libtmux[mcp]``); fastmcp is imported lazily so the rest of
:mod:`libtmux.experimental.mcp` stays dependency-free. :func:`build_server`
projects three layers of tools over one engine:

1. **Curated vocabulary** -- the intuitive, hand-written tools
   (:mod:`~libtmux.experimental.mcp.vocabulary`), always visible.
2. **Per-operation tools** -- one ``op_<kind>`` per registered operation,
   auto-derived from the :class:`~..registry.OperationToolRegistry`. These carry
   a precomputed JSON schema (dynamic params), so each is a :class:`fastmcp.tools.
   Tool` subclass with an explicit ``parameters`` schema rather than an
   introspected signature. Tagged ``per-op`` and hidden by default (the full
   surface is large); ``expose_operations=True`` reveals them.
3. **Plan tools** -- :func:`preview_plan`/:func:`execute_plan`/
   :func:`result_schema`/:func:`build_workspace`, taking serialized operations so
   an agent can compose and run a whole :class:`~..ops.plan.LazyPlan`.

The agent-facing ``engine`` is bound out of each tool's schema, and the safety
tier becomes the tool's ``ToolAnnotations`` + tag.

Examples
--------
>>> import asyncio
>>> from fastmcp import Client  # doctest: +SKIP
>>> from libtmux.experimental.engines import ConcreteEngine
>>> server = build_server(ConcreteEngine())  # doctest: +SKIP
>>> async def main():  # doctest: +SKIP
...     async with Client(server) as client:
...         return (await client.call_tool("create_session", {"name": "dev"})).data
>>> asyncio.run(main())  # doctest: +SKIP
"""

from __future__ import annotations

import dataclasses
import inspect
import typing as t

from libtmux.experimental.mcp import vocabulary
from libtmux.experimental.mcp.registry import OperationToolRegistry

if t.TYPE_CHECKING:
    from collections.abc import Callable

    from fastmcp import FastMCP

    from libtmux.experimental.engines.base import TmuxEngine
    from libtmux.experimental.mcp.descriptor import ToolDescriptor
    from libtmux.experimental.ops.plan import LazyPlan

# (function, safety tier) -- every curated tool takes ``engine`` as its first arg.
_VOCABULARY: tuple[tuple[Callable[..., t.Any], str], ...] = (
    (vocabulary.create_session, "mutating"),
    (vocabulary.create_window, "mutating"),
    (vocabulary.split_pane, "mutating"),
    (vocabulary.send_input, "mutating"),
    (vocabulary.capture_pane, "readonly"),
    (vocabulary.list_sessions, "readonly"),
    (vocabulary.list_windows, "readonly"),
    (vocabulary.list_panes, "readonly"),
    (vocabulary.rename_window, "mutating"),
    (vocabulary.rename_session, "mutating"),
    (vocabulary.select_layout, "mutating"),
    (vocabulary.select_pane, "mutating"),
    (vocabulary.kill_pane, "destructive"),
    (vocabulary.kill_window, "destructive"),
    (vocabulary.kill_session, "destructive"),
)

_INSTRUCTIONS = (
    "Drive tmux through typed tools. Targets accept tmux ids (%pane, @window, "
    "$session), names, or 'session:window.pane'. Creating a session/window also "
    "returns the new first-pane id for chaining. The curated tools cover most "
    "needs; the full per-operation surface (op_*) and the plan tools "
    "(preview_plan/execute_plan/result_schema/build_workspace) are available for "
    "power use."
)

_TARGET_HELP = (
    "tmux target: an id (%pane, @window, $session), a name, or 'session:window.pane'"
)


def _summary(doc: str | None) -> str | None:
    """Return the first non-empty docstring line."""
    for line in (doc or "").splitlines():
        if line.strip():
            return line.strip()
    return None


def _bind_engine(
    fn: Callable[..., t.Any],
    engine: TmuxEngine,
) -> Callable[..., t.Any]:
    """Bind *engine* out of *fn*, returning a wrapper fastmcp can introspect.

    Unlike :func:`functools.partial`, this carries *pre-resolved* annotations
    (with ``engine`` removed) and an explicit ``__signature__``, so fastmcp's
    ``get_type_hints`` never has to re-evaluate the forward references in *fn*
    (it would do so against the wrong module globals and fail).
    """
    hints = t.get_type_hints(fn)
    signature = inspect.signature(fn)
    params = [p for name, p in signature.parameters.items() if name != "engine"]

    def tool(*args: t.Any, **kwargs: t.Any) -> t.Any:
        return fn(engine, *args, **kwargs)

    tool.__name__ = fn.__name__
    tool.__qualname__ = fn.__name__
    tool.__doc__ = fn.__doc__
    tool.__signature__ = signature.replace(parameters=params)  # type: ignore[attr-defined]
    tool.__annotations__ = {k: v for k, v in hints.items() if k != "engine"}
    return tool


def register_vocabulary(mcp: FastMCP, engine: TmuxEngine) -> None:
    """Register the curated vocabulary as tools on *mcp*, bound to *engine*."""
    from fastmcp.tools import FunctionTool
    from mcp.types import ToolAnnotations

    for fn, safety in _VOCABULARY:
        annotations = ToolAnnotations(
            title=fn.__name__,
            readOnlyHint=safety == "readonly",
            destructiveHint=safety == "destructive",
        )
        tool = FunctionTool.from_function(
            _bind_engine(fn, engine),
            name=fn.__name__,
            description=_summary(fn.__doc__),
            tags={safety},
            annotations=annotations,
        )
        mcp.add_tool(tool)


def _op_input_schema(descriptor: ToolDescriptor) -> dict[str, t.Any]:
    """Return the per-op tool's input schema, re-adding the target params.

    The :class:`~..registry.OperationToolRegistry` omits ``target`` /
    ``src_target`` from a descriptor's params (they are polymorphic
    :data:`~..ops._types.Target` values, handled by
    :meth:`~..descriptor.ToolDescriptor.build`), so the schema is re-completed
    here -- at the framework edge -- as plain ``string`` params. Required-ness
    follows the operation field's default.
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
    engine: TmuxEngine,
    *,
    registry: OperationToolRegistry | None = None,
    hidden: bool = True,
) -> None:
    """Register one ``op_<kind>`` tool per registered operation.

    Each tool carries the operation's precomputed JSON schema and dispatches to
    :meth:`~..descriptor.ToolDescriptor.build` + :func:`~..ops.execute.run`,
    returning the serialized result. Tools are tagged ``per-op`` plus their
    safety tier; when *hidden* (the default) the ``per-op`` tag is disabled so
    the large surface does not clutter an agent's tool list (re-enable with
    ``mcp.enable(tags={"per-op"})``).
    """
    from fastmcp.tools import Tool, ToolResult
    from mcp.types import ToolAnnotations
    from pydantic import PrivateAttr

    from libtmux.experimental.ops import run as run_op
    from libtmux.experimental.ops.serialize import result_to_dict

    class _OperationTool(Tool):
        """A per-operation tool: explicit schema + dispatch to the registry."""

        _descriptor: t.Any = PrivateAttr(default=None)
        _engine: t.Any = PrivateAttr(default=None)

        async def run(self, arguments: dict[str, t.Any]) -> ToolResult:
            operation = self._descriptor.build(**arguments)
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
        mcp.add_tool(tool)
    if hidden:
        mcp.disable(tags={"per-op"})


def register_plan_tools(
    mcp: FastMCP,
    engine: TmuxEngine,
    *,
    registry: OperationToolRegistry | None = None,
) -> None:
    """Register the plan-tier tools (compose + run serialized :class:`LazyPlan`s).

    ``preview_plan`` renders without executing; ``execute_plan`` runs a
    serialized plan (forward refs resolved via bindings); ``result_schema``
    reports what a kind returns; ``build_workspace`` builds the Declarative tier
    in one call. All take JSON-serializable inputs (operation dicts from
    :func:`~..ops.serialize.operation_to_dict`).
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
    from libtmux.experimental.ops.serialize import operation_from_dict

    reg = registry if registry is not None else OperationToolRegistry()
    planners: dict[str, type[Planner]] = {
        "sequential": SequentialPlanner,
        "folding": FoldingPlanner,
        "marked": MarkedPlanner,
    }

    def _plan_from_dicts(operations: list[dict[str, t.Any]]) -> LazyPlan:
        plan = LazyPlan()
        for data in operations:
            plan.add(operation_from_dict(data))
        return plan

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

    def execute_plan(
        operations: list[dict[str, t.Any]],
        planner: str = "sequential",
        version: str | None = None,
    ) -> dict[str, t.Any]:
        """Execute a serialized plan over the engine; return results + bindings."""
        chosen = planners.get(planner)
        if chosen is None:
            msg = f"unknown planner {planner!r}; choose from {sorted(planners)}"
            raise ValueError(msg)
        outcome = _plan.execute_plan(
            _plan_from_dicts(operations),
            engine,
            version=version,
            planner=chosen(),
        )
        return {
            "ok": outcome.ok,
            "results": outcome.results,
            "bindings": outcome.bindings,
        }

    def result_schema(kind: str) -> dict[str, t.Any]:
        """Report what an operation kind returns, for planning forward refs."""
        schema = _plan.result_schema(reg, kind)
        return {
            "kind": schema.kind,
            "result_type": schema.result_type,
            "schema": schema.schema,
            "binding_fields": schema.binding_fields,
        }

    def build_workspace(
        spec: dict[str, t.Any],
        preflight: bool = True,
        version: str | None = None,
    ) -> dict[str, t.Any]:
        """Build a declarative workspace (the Declarative tier) in one call."""
        outcome = _plan.build_workspace(
            spec,
            engine,
            version=version,
            preflight=preflight,
        )
        return {
            "ok": outcome.ok,
            "results": outcome.results,
            "bindings": outcome.bindings,
        }

    tools: tuple[tuple[Callable[..., t.Any], str], ...] = (
        (preview_plan, "readonly"),
        (result_schema, "readonly"),
        (execute_plan, "mutating"),
        (build_workspace, "mutating"),
    )
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


def build_server(
    engine: TmuxEngine,
    *,
    name: str = "libtmux-engine",
    instructions: str | None = None,
    include_operations: bool = True,
    expose_operations: bool = False,
    include_plan_tools: bool = True,
) -> FastMCP:
    """Build a FastMCP server exposing the typed tool surface over *engine*.

    Parameters
    ----------
    engine
        The :class:`~..engines.base.TmuxEngine` every tool runs against.
    name, instructions
        Server identity (``instructions`` defaults to a built-in primer).
    include_operations
        Register the auto-derived ``op_<kind>`` per-operation tools.
    expose_operations
        Reveal those per-operation tools by default (otherwise they are
        registered but hidden behind the ``per-op`` tag).
    include_plan_tools
        Register the plan-tier tools.
    """
    from fastmcp import FastMCP

    mcp: FastMCP = FastMCP(name=name, instructions=instructions or _INSTRUCTIONS)
    registry = OperationToolRegistry()
    register_vocabulary(mcp, engine)
    if include_operations:
        register_operations(
            mcp,
            engine,
            registry=registry,
            hidden=not expose_operations,
        )
    if include_plan_tools:
        register_plan_tools(mcp, engine, registry=registry)
    return mcp
