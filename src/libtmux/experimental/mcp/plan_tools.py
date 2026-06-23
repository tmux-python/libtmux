"""Plan-tier tools: preview a plan, execute it (with bindings), introspect.

These wrap the Core :class:`~..ops.plan.LazyPlan` for an agent: a pure dry-run, a
typed execution that returns JSON-serialisable per-op results plus a forward-ref
``bindings`` map, and a result-schema query so an agent can learn what ids a step
will yield *before* composing the next step.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops.serialize import (
    bindings_to_dict,
    operation_to_dict,
    result_to_dict,
)

if t.TYPE_CHECKING:
    from libtmux.experimental.engines.base import AsyncTmuxEngine, TmuxEngine
    from libtmux.experimental.mcp.registry import OperationToolRegistry
    from libtmux.experimental.ops.plan import LazyPlan
    from libtmux.experimental.ops.planner import Planner


@dataclass(frozen=True)
class PlanPreview:
    """A pure dry-run of a plan: per-op dicts + rendered argv (or ``None``)."""

    operations: list[dict[str, t.Any]]
    argv: list[tuple[str, ...] | None]

    @property
    def ok(self) -> bool:
        """Whether every operation rendered (no unresolved forward refs)."""
        return all(item is not None for item in self.argv)


def preview_plan(plan: LazyPlan, *, version: str | None = None) -> PlanPreview:
    """Render a plan without executing it (forward-ref steps render as ``None``)."""
    return PlanPreview(
        operations=[operation_to_dict(op) for op in plan.operations],
        argv=plan.preview(version=version),
    )


@dataclass(frozen=True)
class PlanOutcome:
    """The result of executing a plan: per-op result dicts + a bindings map."""

    ok: bool
    results: list[dict[str, t.Any]]
    bindings: dict[str, str]


def execute_plan(
    plan: LazyPlan,
    engine: TmuxEngine,
    *,
    version: str | None = None,
    planner: Planner | None = None,
) -> PlanOutcome:
    """Execute *plan* over *engine*; return JSON-friendly results + bindings."""
    result = plan.execute(engine, version=version, planner=planner)
    return PlanOutcome(
        ok=result.ok,
        results=[result_to_dict(item) for item in result.results],
        bindings=bindings_to_dict(result.bindings),
    )


async def aexecute_plan(
    plan: LazyPlan,
    engine: AsyncTmuxEngine,
    *,
    version: str | None = None,
    planner: Planner | None = None,
) -> PlanOutcome:
    """Async sibling of :func:`execute_plan` (same shape)."""
    result = await plan.aexecute(engine, version=version, planner=planner)
    return PlanOutcome(
        ok=result.ok,
        results=[result_to_dict(item) for item in result.results],
        bindings=bindings_to_dict(result.bindings),
    )


@dataclass(frozen=True)
class ResultSchema:
    """A result type's schema + the fields an agent can bind downstream."""

    kind: str
    result_type: str
    schema: dict[str, t.Any]
    binding_fields: list[str]


def result_schema(registry: OperationToolRegistry, kind: str) -> ResultSchema:
    """Introspect what *kind* returns -- so an agent can plan forward refs.

    ``binding_fields`` are the result fields carrying ids an agent would reference
    in a later step (``*_id`` / ``new_id``); they are read from the result
    dataclass directly, so they do not depend on the JSON-schema backend.
    """
    import dataclasses

    from libtmux.experimental.ops import registry as ops_registry

    descriptor = registry.descriptor(kind)
    fields = [
        field.name for field in dataclasses.fields(ops_registry.get(kind).result_cls)
    ]
    binding_fields = [
        name for name in fields if name == "new_id" or name.endswith("_id")
    ]
    return ResultSchema(
        kind=kind,
        result_type=descriptor.result_type,
        schema=dict(descriptor.result_schema),
        binding_fields=binding_fields,
    )


def build_workspace(
    spec: t.Mapping[str, t.Any] | str,
    engine: TmuxEngine,
    *,
    version: str | None = None,
    preflight: bool = True,
) -> PlanOutcome:
    """Build a declarative workspace (the Declarative tier) as one tool call.

    *spec* is a tmux-style mapping or YAML string (see
    :func:`~..workspace.analyzer.analyze`).
    """
    from libtmux.experimental.workspace import analyze

    result = analyze(spec).build(engine, version=version, preflight=preflight)
    return PlanOutcome(
        ok=result.ok,
        results=[result_to_dict(item) for item in result.results],
        bindings=bindings_to_dict(result.bindings),
    )
