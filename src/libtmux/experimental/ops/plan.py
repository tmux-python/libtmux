"""Lazy, deferred-resolution plans over the typed operation spine.

A :class:`LazyPlan` records operations without touching tmux, so a plan can be
inspected, serialized, and executed later. Operations may target the *result of
an earlier operation* via a :class:`~._types.SlotRef` (e.g. send keys to the pane
a split is about to create); the plan resolves those references from captured ids
at execution time.

Resolution is a sans-I/O generator -- the same yield-operation / resume-with-
result trampoline the chainable-commands prototype uses. The sync
:meth:`LazyPlan.execute` and async :meth:`LazyPlan.aexecute` drivers differ only
in ``run(...)`` versus ``await arun(...)``; the resolution logic is written once.
"""

from __future__ import annotations

import dataclasses
import typing as t
from dataclasses import dataclass, field

from libtmux.experimental.engines.base import CommandRequest
from libtmux.experimental.ops._chain import (
    attribute,
    attribute_marked,
    render_chain,
    render_marked,
)
from libtmux.experimental.ops._types import (
    PaneId,
    SessionId,
    SlotRef,
    Special,
    WindowId,
)
from libtmux.experimental.ops.exc import ForwardCaptureError
from libtmux.experimental.ops.execute import arun, resolve_engine_version, run
from libtmux.experimental.ops.planner import Planner, PlanStep, SequentialPlanner
from libtmux.experimental.ops.serialize import operation_from_dict, operation_to_dict

if t.TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator, Iterator

    from typing_extensions import Self

    from libtmux.experimental.engines.base import (
        AsyncTmuxEngine,
        CommandResult,
        TmuxEngine,
    )
    from libtmux.experimental.ops._chain import OpChain
    from libtmux.experimental.ops._types import Target
    from libtmux.experimental.ops.operation import Operation
    from libtmux.experimental.ops.results import Result


@dataclass(frozen=True)
class _Single:
    """Drive request: run one resolved operation and return its typed result."""

    op: Operation[t.Any]


@dataclass(frozen=True)
class _Chain:
    """Drive request: dispatch a folded ``;`` chain and return the merged result."""

    argv: tuple[str, ...]


@dataclass(frozen=True)
class StepReport:
    """One executed :class:`~.planner.PlanStep`, reported to a per-step callback.

    Passed to the ``on_step`` hook of :meth:`LazyPlan.execute` /
    :meth:`LazyPlan.aexecute` after each step's results bind, letting a caller
    interleave host-side work (e.g. the workspace runner's sleeps and pane-ready
    waits) *between* dispatches without forking the resolution core.

    Parameters
    ----------
    step : PlanStep
        The dispatch unit that just ran.
    results : tuple[Result, ...]
        The step's per-op results, in ``step.indices`` order.
    bindings : dict[int | tuple[int, str], str]
        The live binding map (same reference the driver mutates), so the callback
        can resolve a :class:`~._types.SlotRef` against already-captured ids.
    """

    step: PlanStep
    results: tuple[Result, ...]
    bindings: dict[int | tuple[int, str], str]


@dataclass(frozen=True)
class _Host:
    """Drive request: fire the per-step host hook; the driver returns ``None``."""

    report: StepReport


@dataclass(frozen=True)
class StepExplanation:
    """Why one dispatch step is its own tmux call (from :meth:`LazyPlan.explain`).

    ``reason`` is one of ``"marked-fold"`` (a pane create plus its ``{marked}``
    decorates), ``"folded"`` (a ``;``-chain of chainable ops), ``"created-id"``
    (a create whose captured id a later op must target -- a true blocker),
    ``"capture"`` (a non-chainable op whose stdout can't merge into a chain), or
    ``"single"`` (a lone chainable op with nothing to fold with).
    """

    step: PlanStep
    kinds: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class StepDone:
    """Stream event: a plan step finished and its results have bound."""

    report: StepReport


@dataclass(frozen=True)
class PlanDone:
    """Stream event: the plan finished; carries the full :class:`PlanResult`."""

    result: PlanResult


#: An event yielded by :meth:`LazyPlan.astream`.
PlanEvent = StepDone | PlanDone


def _target_from_id(value: str) -> Target:
    """Map a captured concrete id back to its typed target."""
    if value.startswith("%"):
        return PaneId(value)
    if value.startswith("@"):
        return WindowId(value)
    if value.startswith("$"):
        return SessionId(value)
    return Special(value)


def _resolve_slot(
    ref: SlotRef,
    bindings: dict[int | tuple[int, str], str],
) -> Target:
    """Map a :class:`SlotRef` to the captured concrete target it points at."""
    key: int | tuple[int, str] = (
        ref.slot if ref.part == "self" else (ref.slot, ref.part)
    )
    try:
        concrete = bindings[key] + ref.suffix
    except KeyError as error:
        raise ForwardCaptureError(ref.slot, ref.part) from error
    return _target_from_id(concrete)


def _resolve(
    operation: Operation[t.Any],
    bindings: dict[int | tuple[int, str], str],
) -> Operation[t.Any]:
    """Substitute any :class:`SlotRef` ``target``/``src_target`` with its id."""
    changes: dict[str, Target] = {}
    if isinstance(operation.target, SlotRef):
        changes["target"] = _resolve_slot(operation.target, bindings)
    if isinstance(operation.src_target, SlotRef):
        changes["src_target"] = _resolve_slot(operation.src_target, bindings)
    if not changes:
        return operation
    return dataclasses.replace(operation, **changes)


def _resolve_src(
    operation: Operation[t.Any],
    bindings: dict[int | tuple[int, str], str],
) -> Operation[t.Any]:
    """Resolve only a :class:`SlotRef` ``src_target``.

    A ``{marked}`` decorate's ``target`` is this same fold's create, which has no
    captured id yet -- it is addressed through tmux's ``{marked}`` register by
    :func:`~._chain.render_marked`, so only ``src_target`` (which references an
    already-bound earlier step) is substituted here.
    """
    if isinstance(operation.src_target, SlotRef):
        return dataclasses.replace(
            operation,
            src_target=_resolve_slot(operation.src_target, bindings),
        )
    return operation


@dataclass(frozen=True)
class PlanResult:
    """The outcome of executing a :class:`LazyPlan`.

    Parameters
    ----------
    results : tuple[Result, ...]
        One result per recorded operation, in order.
    bindings : dict[int | tuple[int, str], str]
        Maps a creating step's index to the concrete id it produced; a
        ``(index, part)`` key holds an implicit child's id (e.g. a new window's
        first pane), bound when the creator opts into capturing it.
    """

    results: tuple[Result, ...]
    bindings: dict[int | tuple[int, str], str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Whether every step completed successfully."""
        return all(result.ok for result in self.results)

    def raise_for_status(self) -> Self:
        """Raise on the first failed step; return ``self`` when all are OK."""
        for result in self.results:
            result.raise_for_status()
        return self


class LazyPlan:
    """Record operations now; resolve refs and execute them later.

    Examples
    --------
    Build a plan that splits a window then types into the *new* pane, and run it
    against the in-memory concrete engine (no tmux required):

    >>> from libtmux.experimental.ops import SplitWindow, SendKeys
    >>> from libtmux.experimental.ops._types import WindowId
    >>> from libtmux.experimental.engines import ConcreteEngine
    >>> plan = LazyPlan()
    >>> pane = plan.add(SplitWindow(target=WindowId("@1")))
    >>> _ = plan.add(SendKeys(target=pane, keys="vim", enter=True))
    >>> outcome = plan.execute(ConcreteEngine())
    >>> outcome.bindings
    {0: '%1'}
    >>> outcome.results[1].argv
    ('send-keys', '-t', '%1', 'vim', 'Enter')
    """

    def __init__(self) -> None:
        self._operations: list[Operation[t.Any]] = []

    def add(self, operation: Operation[t.Any]) -> SlotRef:
        """Record an operation; return a :class:`SlotRef` to its eventual id.

        The returned ref can be used as the ``target`` of a later operation to
        address the object this one creates.
        """
        self._operations.append(operation)
        return SlotRef(len(self._operations) - 1)

    @property
    def operations(self) -> tuple[Operation[t.Any], ...]:
        """The recorded operations, in order."""
        return tuple(self._operations)

    def __len__(self) -> int:
        """Return the number of recorded operations."""
        return len(self._operations)

    def __iter__(self) -> Iterator[Operation[t.Any]]:
        """Iterate recorded operations in order."""
        return iter(self._operations)

    def to_list(self) -> list[dict[str, t.Any]]:
        """Serialize the whole plan to a list of plain operation dicts."""
        return [operation_to_dict(operation) for operation in self._operations]

    @classmethod
    def from_list(cls, data: t.Sequence[t.Mapping[str, t.Any]]) -> LazyPlan:
        """Reconstruct a plan from :meth:`to_list` output."""
        plan = cls()
        plan._operations = [operation_from_dict(item) for item in data]
        return plan

    def add_chain(self, chain: OpChain) -> None:
        """Record every operation of an :class:`~._chain.OpChain` in order."""
        self._operations.extend(chain.ops)

    def preview(self, *, version: str | None = None) -> list[tuple[str, ...] | None]:
        """Render each recorded operation's argv without executing it.

        A pure dry-run: an operation whose target is still an unresolved
        :class:`~._types.SlotRef` renders as ``None`` (it needs a captured id
        from an earlier step, supplied only at execution time).

        Examples
        --------
        >>> from libtmux.experimental.ops import SplitWindow, SendKeys
        >>> from libtmux.experimental.ops._types import WindowId
        >>> plan = LazyPlan()
        >>> pane = plan.add(SplitWindow(target=WindowId("@1")))
        >>> _ = plan.add(SendKeys(target=pane, keys="vim", enter=True))
        >>> plan.preview()
        [('split-window', '-t', '@1', '-v', '-P', '-F', '#{pane_id}'), None]
        """

        def _render(op: Operation[t.Any]) -> tuple[str, ...] | None:
            try:
                return op.render(version=version)
            except TypeError:  # unresolved SlotRef -- needs a captured id
                return None

        return [_render(op) for op in self._operations]

    def explain(self, planner: Planner | None = None) -> list[StepExplanation]:
        """Explain why *planner* breaks the plan into the dispatches it does.

        A pure companion to :meth:`preview`: folding hides per-op structure, so
        this annotates each dispatch step with the reason it can't fold further
        (see :class:`StepExplanation`). Defaults to
        :class:`~.planner.SequentialPlanner`.

        Examples
        --------
        >>> from libtmux.experimental.ops import SplitWindow, SendKeys, MarkedPlanner
        >>> from libtmux.experimental.ops._types import WindowId
        >>> plan = LazyPlan()
        >>> pane = plan.add(SplitWindow(target=WindowId("@1")))
        >>> _ = plan.add(SendKeys(target=pane, keys="vim"))
        >>> [(e.kinds, e.reason) for e in plan.explain(MarkedPlanner())]
        [(('split_window', 'send_keys'), 'marked-fold')]
        >>> [(e.kinds, e.reason) for e in plan.explain()]
        [(('split_window',), 'created-id'), (('send_keys',), 'single')]
        """
        steps = (planner or SequentialPlanner()).plan(self._operations)
        out: list[StepExplanation] = []
        for step in steps:
            kinds = tuple(self._operations[i].kind for i in step.indices)
            if step.marked:
                reason = "marked-fold"
            elif len(step.indices) > 1:
                reason = "folded"
            else:
                op = self._operations[step.indices[0]]
                if op.effects.creates is not None:
                    reason = "created-id"
                elif not op.chainable:
                    reason = "capture"
                else:
                    reason = "single"
            out.append(StepExplanation(step, kinds, reason))
        return out

    def _drive(
        self,
        version: str | None,
        planner: Planner,
    ) -> Generator[_Single | _Chain | _Host, t.Any, PlanResult]:
        """Sans-I/O resolution core driven by a :class:`~.planner.Planner`.

        Yields a :class:`_Single` (driver runs one op, returns its
        :class:`~.results.Result`), a :class:`_Chain` (driver returns the merged
        :class:`~..engines.base.CommandResult`, attributed per op here), or a
        :class:`_Host` once per step *after* its results bind (driver fires the
        ``on_step`` hook, returns ``None``). The generator performs no host I/O
        itself -- the host hook is the single colored leaf the drivers fork on.
        The sync and async drivers differ only in ``run`` vs ``await arun`` and
        ``engine.run`` vs ``await engine.run``.
        """
        bindings: dict[int | tuple[int, str], str] = {}
        results: dict[int, Result] = {}
        for step in planner.plan(self._operations):
            if step.marked:
                create_idx, *decorate_idx = step.indices
                create = _resolve(self._operations[create_idx], bindings)
                decorates = [
                    _resolve_src(self._operations[i], bindings) for i in decorate_idx
                ]
                merged: CommandResult = yield _Chain(
                    render_marked(create, decorates, version),
                )
                created, decorated, new_id = attribute_marked(
                    create,
                    decorates,
                    merged,
                    version,
                )
                results[create_idx] = created
                results.update(zip(decorate_idx, decorated, strict=True))
                if new_id is not None:
                    bindings[create_idx] = new_id
            elif len(step.indices) == 1:
                index = step.indices[0]
                result = yield _Single(_resolve(self._operations[index], bindings))
                results[index] = result
                if result.created_id is not None:
                    bindings[index] = result.created_id
                for sub_part, sub_id in result.created_subids.items():
                    bindings[index, sub_part] = sub_id
            else:
                group = [_resolve(self._operations[i], bindings) for i in step.indices]
                merged = yield _Chain(render_chain(group, version))
                results.update(
                    zip(step.indices, attribute(group, merged, version), strict=True),
                )
            ordered_step = tuple(results[i] for i in step.indices)
            yield _Host(StepReport(step, ordered_step, bindings))
        ordered = tuple(results[slot] for slot in range(len(self._operations)))
        return PlanResult(ordered, bindings)

    def execute(
        self,
        engine: TmuxEngine,
        *,
        version: str | None = None,
        planner: Planner | None = None,
        on_step: t.Callable[[StepReport], None] | None = None,
    ) -> PlanResult:
        """Resolve and execute the plan synchronously.

        The *planner* decides dispatch grouping; it defaults to
        :class:`~.planner.SequentialPlanner` (one tmux call per op). Pass a
        :class:`~.planner.FoldingPlanner` or :class:`~.planner.MarkedPlanner` to
        fold dispatches -- the :class:`PlanResult` is identical, only the
        dispatch count changes.

        *on_step* is called with a :class:`StepReport` after each step's results
        bind, so a caller can interleave host-side work between dispatches; it is
        a no-op trampoline hop when ``None``.
        """
        version = resolve_engine_version(engine, version)
        gen = self._drive(version, planner or SequentialPlanner())
        try:
            request = next(gen)
            while True:
                if isinstance(request, _Host):
                    if on_step is not None:
                        on_step(request.report)
                    request = gen.send(None)
                else:
                    request = gen.send(self._dispatch(request, engine, version))
        except StopIteration as stop:
            return t.cast("PlanResult", stop.value)

    def _dispatch(
        self,
        request: _Single | _Chain,
        engine: TmuxEngine,
        version: str | None,
    ) -> t.Any:
        """Run one drive request synchronously."""
        if isinstance(request, _Chain):
            return engine.run(CommandRequest.from_args(*request.argv))
        return run(request.op, engine, version=version)

    async def aexecute(
        self,
        engine: AsyncTmuxEngine,
        *,
        version: str | None = None,
        planner: Planner | None = None,
        on_step: t.Callable[[StepReport], t.Awaitable[None]] | None = None,
    ) -> PlanResult:
        """Resolve and execute the plan asynchronously (same resolution core).

        Mirrors :meth:`execute`; *on_step* is awaited per step.
        """
        version = resolve_engine_version(engine, version)
        gen = self._drive(version, planner or SequentialPlanner())
        try:
            request = next(gen)
            while True:
                if isinstance(request, _Host):
                    if on_step is not None:
                        await on_step(request.report)
                    request = gen.send(None)
                else:
                    request = gen.send(await self._adispatch(request, engine, version))
        except StopIteration as stop:
            return t.cast("PlanResult", stop.value)

    async def _adispatch(
        self,
        request: _Single | _Chain,
        engine: AsyncTmuxEngine,
        version: str | None,
    ) -> t.Any:
        """Run one drive request asynchronously (async twin of :meth:`_dispatch`)."""
        if isinstance(request, _Chain):
            return await engine.run(CommandRequest.from_args(*request.argv))
        return await arun(request.op, engine, version=version)

    async def astream(
        self,
        engine: AsyncTmuxEngine,
        *,
        version: str | None = None,
        planner: Planner | None = None,
    ) -> AsyncGenerator[PlanEvent, None]:
        """Execute the plan, streaming a :data:`PlanEvent` per step as it binds.

        The observe-as-you-go twin of :meth:`aexecute` over the same sans-I/O
        resolution core: it yields a :class:`StepDone` after each dispatch binds
        and a terminal :class:`PlanDone` carrying the full :class:`PlanResult`, so
        ``[e async for e in plan.astream(engine)][-1].result`` equals ``await
        plan.aexecute(engine)``. The stream is pull-based -- a slow ``async for``
        naturally paces the plan, so backpressure needs no buffer and the event
        loop is never blocked between dispatches. Run one ``astream`` per engine
        at a time (the engine's write order is shared).

        Examples
        --------
        >>> import asyncio
        >>> from libtmux.experimental.engines.concrete import AsyncConcreteEngine
        >>> from libtmux.experimental.ops import SendKeys
        >>> from libtmux.experimental.ops._types import PaneId
        >>> plan = LazyPlan()
        >>> _ = plan.add(SendKeys(target=PaneId("%1"), keys="vim"))
        >>> async def drain() -> list[str]:
        ...     engine = AsyncConcreteEngine()
        ...     return [type(e).__name__ async for e in plan.astream(engine)]
        >>> asyncio.run(drain())
        ['StepDone', 'PlanDone']
        """
        version = resolve_engine_version(engine, version)
        gen = self._drive(version, planner or SequentialPlanner())
        try:
            request = next(gen)
            while True:
                if isinstance(request, _Host):
                    yield StepDone(request.report)  # pull point: consumer paces here
                    request = gen.send(None)
                else:
                    request = gen.send(await self._adispatch(request, engine, version))
        except StopIteration as stop:
            yield PlanDone(t.cast("PlanResult", stop.value))
