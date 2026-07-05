"""Execute a compiled workspace over any engine, sync or async.

The runner is the Declarative tier's *bound* layer. It drives the compiled plan
through Core's :meth:`~libtmux.experimental.ops.plan.LazyPlan.execute` so the
build reuses the same sans-I/O resolution trampoline as any other plan -- and so
folds dispatches via a :class:`~..ops.planner.Planner`. Host-side steps (sleep /
before_script / pane-readiness waits) must run *between* tmux dispatches, so the
compiler records them as a separate schedule keyed by operation index
(:attr:`~..compiler.Compiled.host_after`). The runner turns those keys into fold
boundaries via a :class:`~..ops.planner.BoundedPlanner` (no fold may cross a host
step) and replays each index's host steps from the ``on_step`` hook
:meth:`~..ops.plan.LazyPlan.execute` fires after every step binds. Idempotent
replace is handled *around* the build via a ``has-session`` pre-check.

The same compiled plan runs identically through any engine and through either the
sync (:func:`build_workspace`) or async (:func:`abuild_workspace`) driver -- the
only difference is ``run`` vs ``await arun`` and the host-step executor.

``preflight=False`` skips the ``on_exists`` ``has-session`` check; use it offline
against the stateless ``MockEngine`` (whose ``has-session`` is always true).
"""

from __future__ import annotations

import asyncio
import subprocess
import time
import typing as t

from libtmux.experimental.ops import (
    DisplayMessage,
    HasSession,
    KillSession,
    arun,
    run,
)
from libtmux.experimental.ops._types import NameRef
from libtmux.experimental.ops.plan import PlanResult, StepReport, _resolve
from libtmux.experimental.ops.planner import BoundedPlanner, MarkedPlanner
from libtmux.experimental.workspace.compiler import compile_full
from libtmux.experimental.workspace.events import WorkspaceBuilt, events_for

if t.TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from libtmux.experimental.engines.base import AsyncTmuxEngine, TmuxEngine
    from libtmux.experimental.ops.planner import Planner
    from libtmux.experimental.workspace.compiler import HostStep
    from libtmux.experimental.workspace.events import BuildEvent
    from libtmux.experimental.workspace.ir import Workspace


#: Pane-readiness poll budget: ~2s at a 50ms cadence (matches tmuxp's timeout).
_WAIT_PANE_POLLS = 40
_WAIT_PANE_INTERVAL = 0.05
_CURSOR_FMT = "#{cursor_x},#{cursor_y}"


def _pane_ready(cursor: str) -> bool:
    """Whether the pane's cursor has left the origin (its shell prompt drew)."""
    return bool(cursor) and cursor != "0,0"


def _run_host_sync(
    step: HostStep,
    engine: TmuxEngine,
    bindings: dict[int | tuple[int, str], str],
    version: str | None,
) -> None:
    """Execute one host step synchronously."""
    if step.kind == "sleep" and step.seconds is not None:
        time.sleep(step.seconds)
    elif step.kind == "script" and step.command is not None:
        subprocess.run(step.command, shell=True, cwd=step.cwd, check=False)
    elif step.kind == "wait_pane" and step.pane is not None:
        op = _resolve(DisplayMessage(target=step.pane, message=_CURSOR_FMT), bindings)
        for _ in range(_WAIT_PANE_POLLS):
            if _pane_ready(run(op, engine, version=version).text):
                return
            time.sleep(_WAIT_PANE_INTERVAL)


async def _run_host_async(
    step: HostStep,
    engine: AsyncTmuxEngine,
    bindings: dict[int | tuple[int, str], str],
    version: str | None,
) -> None:
    """Execute one host step asynchronously."""
    if step.kind == "sleep" and step.seconds is not None:
        await asyncio.sleep(step.seconds)
    elif step.kind == "script" and step.command is not None:
        proc = await asyncio.create_subprocess_shell(step.command, cwd=step.cwd)
        await proc.wait()
    elif step.kind == "wait_pane" and step.pane is not None:
        op = _resolve(DisplayMessage(target=step.pane, message=_CURSOR_FMT), bindings)
        for _ in range(_WAIT_PANE_POLLS):
            result = await arun(op, engine, version=version)
            if _pane_ready(result.text):
                return
            await asyncio.sleep(_WAIT_PANE_INTERVAL)


def _preflight_sync(ws: Workspace, engine: TmuxEngine, version: str | None) -> bool:
    """Apply the ``on_exists`` policy; return ``True`` if the build should skip."""
    exists = run(HasSession(target=NameRef(ws.name)), engine, version=version).exists
    if not exists:
        return False
    if ws.on_exists == "replace":
        run(KillSession(target=NameRef(ws.name)), engine, version=version)
        return False
    if ws.on_exists == "reuse":
        return True
    msg = f"session {ws.name!r} already exists (on_exists='error')"
    raise FileExistsError(msg)


async def _preflight_async(
    ws: Workspace,
    engine: AsyncTmuxEngine,
    version: str | None,
) -> bool:
    """Async sibling of :func:`_preflight_sync`."""
    result = await arun(HasSession(target=NameRef(ws.name)), engine, version=version)
    if not result.exists:
        return False
    if ws.on_exists == "replace":
        await arun(KillSession(target=NameRef(ws.name)), engine, version=version)
        return False
    if ws.on_exists == "reuse":
        return True
    msg = f"session {ws.name!r} already exists (on_exists='error')"
    raise FileExistsError(msg)


def build_workspace(
    ws: Workspace,
    engine: TmuxEngine,
    *,
    version: str | None = None,
    preflight: bool = True,
    on_event: Callable[[BuildEvent], None] | None = None,
    planner: Planner | None = None,
) -> PlanResult:
    """Compile and execute *ws* synchronously over *engine*.

    Pass *on_event* to observe the structural build stream (session -> windows ->
    panes -> built) as each operation binds its id.

    The build folds dispatches by default (a :class:`~..ops.planner.MarkedPlanner`
    wrapped so no fold crosses a host step), so a multi-pane window costs a few
    tmux calls instead of one per op. Pass *planner* to override -- e.g.
    :class:`~..ops.planner.SequentialPlanner` for one legible call per op. The
    :class:`~..ops.plan.PlanResult` is identical either way; only the dispatch
    count changes.

    Examples
    --------
    >>> from libtmux.experimental.engines import MockEngine
    >>> from libtmux.experimental.workspace.ir import Workspace, Window, Pane
    >>> ws = Workspace(name="dev", windows=[Window("w", panes=[Pane(run="vim")])])
    >>> build_workspace(ws, MockEngine(), preflight=False).ok
    True
    """
    if preflight and _preflight_sync(ws, engine, version):
        return PlanResult((), {})
    compiled = compile_full(ws, version=version)
    ops = compiled.plan.operations
    for step in compiled.pre:
        _run_host_sync(step, engine, {}, version)

    def on_step(report: StepReport) -> None:
        for index, result in zip(report.step.indices, report.results, strict=True):
            if on_event is not None:
                for event in events_for(ops[index], result):
                    on_event(event)
            for host_step in compiled.host_after.get(index, ()):
                _run_host_sync(host_step, engine, report.bindings, version)

    outcome = compiled.plan.execute(
        engine,
        version=version,
        planner=BoundedPlanner(
            planner or MarkedPlanner(),
            frozenset(compiled.host_after),
        ),
        on_step=on_step,
    )
    if on_event is not None:
        on_event(WorkspaceBuilt(outcome.bindings.get(0, "")))
    return outcome


async def abuild_workspace(
    ws: Workspace,
    engine: AsyncTmuxEngine,
    *,
    version: str | None = None,
    preflight: bool = True,
    on_event: Callable[[BuildEvent], Awaitable[None]] | None = None,
    planner: Planner | None = None,
) -> PlanResult:
    """Compile and execute *ws* asynchronously over *engine* (same resolution).

    *on_event* is awaited inline on the coroutine that runs the interleaved host
    steps and drives the next dispatch, so it must return promptly and must not
    re-enter *engine* (``Awaitable[None]`` cannot enforce this). A slow network
    or render sink should own its own buffer and drain independently -- e.g. the
    ``register_events`` + ``_EventRing``-over-``engine.subscribe()`` pattern in
    ``libtmux.experimental.mcp.events``. Folds by default; see
    :func:`build_workspace` for the *planner* knob.
    """
    if preflight and await _preflight_async(ws, engine, version):
        return PlanResult((), {})
    compiled = compile_full(ws, version=version)
    ops = compiled.plan.operations
    for step in compiled.pre:
        await _run_host_async(step, engine, {}, version)

    # on_event is awaited inline (keep it fast/non-reentrant); a future buffered
    # mode must back-pressure a bounded queue, never drop -- every BuildEvent
    # carries a unique tmux id that must arrive exactly once.
    async def on_step(report: StepReport) -> None:
        for index, result in zip(report.step.indices, report.results, strict=True):
            if on_event is not None:
                for event in events_for(ops[index], result):
                    await on_event(event)
            for host_step in compiled.host_after.get(index, ()):
                await _run_host_async(host_step, engine, report.bindings, version)

    outcome = await compiled.plan.aexecute(
        engine,
        version=version,
        planner=BoundedPlanner(
            planner or MarkedPlanner(),
            frozenset(compiled.host_after),
        ),
        on_step=on_step,
    )
    if on_event is not None:
        await on_event(WorkspaceBuilt(outcome.bindings.get(0, "")))
    return outcome
