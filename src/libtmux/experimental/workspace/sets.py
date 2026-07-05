"""Batch declarative workspaces into one folded Core plan.

``WorkspaceSet`` is the Declarative tier's collection primitive: a group of
workspace specs that compile into one :class:`~libtmux.experimental.ops.LazyPlan`
and therefore run through the same chainable, async-capable engine path as a
single workspace. It is deliberately still a library value -- no database, server
process, or product workflow -- so callers can layer worktrees, dashboards, or
agent launch policy outside libtmux.
"""

from __future__ import annotations

import dataclasses
import typing as t
from dataclasses import dataclass, field

from libtmux.experimental.ops import HasSession, KillSession, LazyPlan, arun, run
from libtmux.experimental.ops._types import NameRef, SlotRef, Target
from libtmux.experimental.ops.plan import PlanResult, StepReport
from libtmux.experimental.ops.planner import BoundedPlanner, MarkedPlanner
from libtmux.experimental.workspace.compiler import Compiled, HostStep, compile_full
from libtmux.experimental.workspace.events import WorkspaceBuilt, events_for
from libtmux.experimental.workspace.expand import (
    NameFactory,
    Variant,
    expand,
)
from libtmux.experimental.workspace.runner import _run_host_async, _run_host_sync

if t.TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Mapping

    from typing_extensions import Self

    from libtmux.experimental.engines.base import AsyncTmuxEngine, TmuxEngine
    from libtmux.experimental.ops.operation import Operation
    from libtmux.experimental.ops.planner import Planner
    from libtmux.experimental.workspace.events import BuildEvent
    from libtmux.experimental.workspace.ir import Workspace


@dataclass(frozen=True)
class CompiledWorkspaceSet:
    """A merged workspace-set plan plus batch metadata.

    Parameters
    ----------
    plan : LazyPlan
        The combined Core operation spine.
    host_after : Mapping[int, tuple[HostStep, ...]]
        Host steps scheduled after rebased operation indices.
    pre : tuple[HostStep, ...]
        Host steps to run before the first operation.
    sessions : tuple[str, ...]
        Session names in the input order.
    session_slots : Mapping[str, int]
        The plan index of each workspace's ``new-session`` operation.
    end_indices : Mapping[str, int]
        The final operation index for each workspace.
    """

    plan: LazyPlan
    host_after: Mapping[int, tuple[HostStep, ...]] = field(default_factory=dict)
    pre: tuple[HostStep, ...] = ()
    sessions: tuple[str, ...] = ()
    session_slots: Mapping[str, int] = field(default_factory=dict)
    end_indices: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkspaceSetResult:
    """Result of building a workspace set."""

    result: PlanResult
    sessions: tuple[str, ...]
    reused: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """Whether every dispatched operation completed successfully."""
        return self.result.ok

    @property
    def bindings(self) -> dict[int | tuple[int, str], str]:
        """Forward-ref bindings from the underlying plan result."""
        return self.result.bindings

    def raise_for_status(self) -> Self:
        """Raise on the first failed operation; return ``self`` when OK."""
        self.result.raise_for_status()
        return self


@dataclass(frozen=True)
class WorkspaceSet:
    """A collection of declared workspaces compiled and built as one unit.

    Examples
    --------
    >>> from libtmux.experimental.engines import MockEngine
    >>> from libtmux.experimental.workspace import Pane, Window, Workspace
    >>> ws = Workspace("dev", windows=[Window("w", panes=[Pane("echo hi")])])
    >>> WorkspaceSet((ws,)).build(MockEngine(), preflight=False).ok
    True
    """

    workspaces: tuple[Workspace, ...]

    def __init__(self, workspaces: Iterable[Workspace]) -> None:
        object.__setattr__(self, "workspaces", _workspace_tuple(workspaces))

    @classmethod
    def from_variants(
        cls,
        workspace: Workspace,
        variants: Iterable[Variant],
        *,
        variables: Mapping[str, object] | None = None,
        name: NameFactory | None = None,
    ) -> WorkspaceSet:
        """Expand *workspace* over *variants* and wrap the rendered specs."""
        return cls(expand(workspace, variants, variables=variables, name=name))

    def compile(self, *, version: str | None = None) -> CompiledWorkspaceSet:
        """Compile this set into one rebased Core plan."""
        return compile_workspaces(self.workspaces, version=version)

    def build(
        self,
        engine: TmuxEngine,
        *,
        version: str | None = None,
        preflight: bool = True,
        on_event: Callable[[BuildEvent], None] | None = None,
        planner: Planner | None = None,
    ) -> WorkspaceSetResult:
        """Build this set synchronously over *engine*."""
        return build_workspaces(
            self.workspaces,
            engine,
            version=version,
            preflight=preflight,
            on_event=on_event,
            planner=planner,
        )

    async def abuild(
        self,
        engine: AsyncTmuxEngine,
        *,
        version: str | None = None,
        preflight: bool = True,
        on_event: Callable[[BuildEvent], Awaitable[None]] | None = None,
        planner: Planner | None = None,
    ) -> WorkspaceSetResult:
        """Build this set asynchronously over *engine*."""
        return await abuild_workspaces(
            self.workspaces,
            engine,
            version=version,
            preflight=preflight,
            on_event=on_event,
            planner=planner,
        )


def _workspace_tuple(workspaces: Iterable[Workspace]) -> tuple[Workspace, ...]:
    """Return workspaces as a tuple, rejecting duplicate session names."""
    rows = tuple(workspaces)
    seen: set[str] = set()
    duplicates: list[str] = []
    for workspace in rows:
        if workspace.name in seen:
            duplicates.append(workspace.name)
        seen.add(workspace.name)
    if duplicates:
        msg = f"workspace set declares duplicate sessions: {', '.join(duplicates)}"
        raise ValueError(msg)
    return rows


def _rebase_slot(ref: SlotRef, offset: int) -> SlotRef:
    """Return *ref* shifted by *offset* operation slots."""
    return dataclasses.replace(ref, slot=ref.slot + offset)


def _rebase_target(target: Target | None, offset: int) -> Target | None:
    """Shift deferred targets by *offset* while leaving concrete ids unchanged."""
    if isinstance(target, SlotRef):
        return _rebase_slot(target, offset)
    return target


def _rebase_operation(operation: Operation[t.Any], offset: int) -> Operation[t.Any]:
    """Shift operation targets from a per-workspace plan into the merged plan."""
    return dataclasses.replace(
        operation,
        target=_rebase_target(operation.target, offset),
        src_target=_rebase_target(operation.src_target, offset),
    )


def _rebase_host_step(step: HostStep, offset: int) -> HostStep:
    """Shift the pane ref carried by a host step, if any."""
    if step.pane is None:
        return step
    return dataclasses.replace(step, pane=_rebase_slot(step.pane, offset))


def _extend_plan(plan: LazyPlan, compiled: Compiled, offset: int) -> None:
    """Append one compiled workspace to *plan* with rebased refs."""
    for operation in compiled.plan.operations:
        plan.add(_rebase_operation(operation, offset))


def compile_workspaces(
    workspaces: Iterable[Workspace],
    *,
    version: str | None = None,
) -> CompiledWorkspaceSet:
    """Compile multiple workspaces into one rebased Core plan.

    Examples
    --------
    >>> from libtmux.experimental.workspace import Pane, Window, Workspace
    >>> compiled = compile_workspaces([
    ...     Workspace("a", windows=[Window("w", panes=[Pane("one")])]),
    ...     Workspace("b", windows=[Window("w", panes=[Pane("two")])]),
    ... ])
    >>> [op.kind for op in compiled.plan.operations].count("new_session")
    2
    """
    rows = _workspace_tuple(workspaces)
    plan = LazyPlan()
    pre: list[HostStep] = []
    host_after: dict[int, list[HostStep]] = {}
    session_slots: dict[str, int] = {}
    end_indices: dict[str, int] = {}

    for workspace in rows:
        offset = len(plan)
        compiled = compile_full(workspace, version=version)
        if offset == 0:
            pre.extend(_rebase_host_step(step, offset) for step in compiled.pre)
        elif compiled.pre:
            host_after.setdefault(offset - 1, []).extend(
                _rebase_host_step(step, offset) for step in compiled.pre
            )

        for index, steps in compiled.host_after.items():
            host_after.setdefault(index + offset, []).extend(
                _rebase_host_step(step, offset) for step in steps
            )

        _extend_plan(plan, compiled, offset)
        if len(compiled.plan) > 0:
            session_slots[workspace.name] = offset
            end_indices[workspace.name] = offset + len(compiled.plan) - 1

    return CompiledWorkspaceSet(
        plan,
        {key: tuple(value) for key, value in host_after.items()},
        tuple(pre),
        tuple(workspace.name for workspace in rows),
        session_slots,
        end_indices,
    )


def _preflight_sync(
    workspace: Workspace,
    engine: TmuxEngine,
    version: str | None,
) -> bool:
    """Apply one workspace's ``on_exists`` policy before a batch build."""
    exists = run(HasSession(target=NameRef(workspace.name)), engine, version=version)
    if not exists.exists:
        return False
    if workspace.on_exists == "replace":
        run(KillSession(target=NameRef(workspace.name)), engine, version=version)
        return False
    if workspace.on_exists == "reuse":
        return True
    msg = f"session {workspace.name!r} already exists (on_exists='error')"
    raise FileExistsError(msg)


async def _preflight_async(
    workspace: Workspace,
    engine: AsyncTmuxEngine,
    version: str | None,
) -> bool:
    """Async sibling of :func:`_preflight_sync`."""
    result = await arun(
        HasSession(target=NameRef(workspace.name)),
        engine,
        version=version,
    )
    if not result.exists:
        return False
    if workspace.on_exists == "replace":
        await arun(KillSession(target=NameRef(workspace.name)), engine, version=version)
        return False
    if workspace.on_exists == "reuse":
        return True
    msg = f"session {workspace.name!r} already exists (on_exists='error')"
    raise FileExistsError(msg)


def _split_reused_sync(
    workspaces: tuple[Workspace, ...],
    engine: TmuxEngine,
    version: str | None,
    preflight: bool,
) -> tuple[tuple[Workspace, ...], tuple[str, ...]]:
    """Return workspaces to build plus names skipped by ``on_exists='reuse'``."""
    if not preflight:
        return workspaces, ()
    active: list[Workspace] = []
    reused: list[str] = []
    for workspace in workspaces:
        if _preflight_sync(workspace, engine, version):
            reused.append(workspace.name)
        else:
            active.append(workspace)
    return tuple(active), tuple(reused)


async def _split_reused_async(
    workspaces: tuple[Workspace, ...],
    engine: AsyncTmuxEngine,
    version: str | None,
    preflight: bool,
) -> tuple[tuple[Workspace, ...], tuple[str, ...]]:
    """Async sibling of :func:`_split_reused_sync`."""
    if not preflight:
        return workspaces, ()
    active: list[Workspace] = []
    reused: list[str] = []
    for workspace in workspaces:
        if await _preflight_async(workspace, engine, version):
            reused.append(workspace.name)
        else:
            active.append(workspace)
    return tuple(active), tuple(reused)


def build_workspaces(
    workspaces: Iterable[Workspace],
    engine: TmuxEngine,
    *,
    version: str | None = None,
    preflight: bool = True,
    on_event: Callable[[BuildEvent], None] | None = None,
    planner: Planner | None = None,
) -> WorkspaceSetResult:
    """Compile and execute multiple workspaces synchronously over *engine*."""
    rows = _workspace_tuple(workspaces)
    active, reused = _split_reused_sync(rows, engine, version, preflight)
    if not active:
        return WorkspaceSetResult(
            PlanResult((), {}),
            tuple(ws.name for ws in rows),
            reused,
        )

    compiled = compile_workspaces(active, version=version)
    ops = compiled.plan.operations
    end_to_session = {index: name for name, index in compiled.end_indices.items()}
    for step in compiled.pre:
        _run_host_sync(step, engine, {}, version)

    def on_step(report: StepReport) -> None:
        for index, result in zip(report.step.indices, report.results, strict=True):
            if on_event is not None:
                for event in events_for(ops[index], result):
                    on_event(event)
            for host_step in compiled.host_after.get(index, ()):
                _run_host_sync(host_step, engine, report.bindings, version)
            if on_event is not None and index in end_to_session:
                slot = compiled.session_slots[end_to_session[index]]
                on_event(WorkspaceBuilt(report.bindings.get(slot, "")))

    result = compiled.plan.execute(
        engine,
        version=version,
        planner=BoundedPlanner(
            planner or MarkedPlanner(),
            frozenset(compiled.host_after),
        ),
        on_step=on_step,
    )
    return WorkspaceSetResult(result, tuple(ws.name for ws in rows), reused)


async def abuild_workspaces(
    workspaces: Iterable[Workspace],
    engine: AsyncTmuxEngine,
    *,
    version: str | None = None,
    preflight: bool = True,
    on_event: Callable[[BuildEvent], Awaitable[None]] | None = None,
    planner: Planner | None = None,
) -> WorkspaceSetResult:
    """Compile and execute multiple workspaces asynchronously over *engine*.

    *on_event* has the same inline-await contract as :func:`abuild_workspace`:
    keep it fast and non-reentrant, or buffer and drain it yourself.
    """
    rows = _workspace_tuple(workspaces)
    active, reused = await _split_reused_async(rows, engine, version, preflight)
    if not active:
        return WorkspaceSetResult(
            PlanResult((), {}),
            tuple(ws.name for ws in rows),
            reused,
        )

    compiled = compile_workspaces(active, version=version)
    ops = compiled.plan.operations
    end_to_session = {index: name for name, index in compiled.end_indices.items()}
    for step in compiled.pre:
        await _run_host_async(step, engine, {}, version)

    async def on_step(report: StepReport) -> None:
        for index, result in zip(report.step.indices, report.results, strict=True):
            if on_event is not None:
                for event in events_for(ops[index], result):
                    await on_event(event)
            for host_step in compiled.host_after.get(index, ()):
                await _run_host_async(host_step, engine, report.bindings, version)
            if on_event is not None and index in end_to_session:
                slot = compiled.session_slots[end_to_session[index]]
                await on_event(WorkspaceBuilt(report.bindings.get(slot, "")))

    result = await compiled.plan.aexecute(
        engine,
        version=version,
        planner=BoundedPlanner(
            planner or MarkedPlanner(),
            frozenset(compiled.host_after),
        ),
        on_step=on_step,
    )
    return WorkspaceSetResult(result, tuple(ws.name for ws in rows), reused)
