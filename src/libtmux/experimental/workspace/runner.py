"""Execute a compiled workspace over any engine, sync or async.

The runner is the Declarative tier's *bound* layer. It keeps the Core operation
spine pure: it drives the compiled plan one operation at a time (reusing Core's
:func:`~libtmux.experimental.ops.plan._resolve` forward-ref resolution) and
interleaves host-side steps (sleep / before_script) *between* operations rather
than weaving them into Core's ``_drive`` generator. Idempotent replace is handled
*around* the build via a ``has-session`` pre-check.

The same compiled plan runs identically through any engine and through either the
sync (:func:`build_workspace`) or async (:func:`abuild_workspace`) driver -- the
only difference is ``run`` vs ``await arun`` and the host-step executor.

``preflight=False`` skips the ``on_exists`` ``has-session`` check; use it offline
against the stateless ``ConcreteEngine`` (whose ``has-session`` is always true).
"""

from __future__ import annotations

import asyncio
import subprocess
import time
import typing as t

from libtmux.experimental.ops import HasSession, KillSession, arun, run
from libtmux.experimental.ops._types import NameRef
from libtmux.experimental.ops.plan import PlanResult, _resolve
from libtmux.experimental.workspace.compiler import compile_full
from libtmux.experimental.workspace.events import WorkspaceBuilt, events_for

if t.TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from libtmux.experimental.engines.base import AsyncTmuxEngine, TmuxEngine
    from libtmux.experimental.ops.results import Result
    from libtmux.experimental.workspace.compiler import HostStep
    from libtmux.experimental.workspace.events import BuildEvent
    from libtmux.experimental.workspace.ir import Workspace


def _run_host_sync(step: HostStep) -> None:
    """Execute one host step synchronously."""
    if step.kind == "sleep" and step.seconds is not None:
        time.sleep(step.seconds)
    elif step.kind == "script" and step.command is not None:
        subprocess.run(step.command, shell=True, cwd=step.cwd, check=False)


async def _run_host_async(step: HostStep) -> None:
    """Execute one host step asynchronously."""
    if step.kind == "sleep" and step.seconds is not None:
        await asyncio.sleep(step.seconds)
    elif step.kind == "script" and step.command is not None:
        proc = await asyncio.create_subprocess_shell(step.command, cwd=step.cwd)
        await proc.wait()


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
) -> PlanResult:
    """Compile and execute *ws* synchronously over *engine*.

    Pass *on_event* to observe the structural build stream (session -> windows ->
    panes -> built) as each operation binds its id.

    Examples
    --------
    >>> from libtmux.experimental.engines import ConcreteEngine
    >>> from libtmux.experimental.workspace.ir import Workspace, Window, Pane
    >>> ws = Workspace(name="dev", windows=[Window("w", panes=[Pane(run="vim")])])
    >>> build_workspace(ws, ConcreteEngine(), preflight=False).ok
    True
    """
    if preflight and _preflight_sync(ws, engine, version):
        return PlanResult((), {})
    compiled = compile_full(ws, version=version)
    for step in compiled.pre:
        _run_host_sync(step)
    bindings: dict[int | tuple[int, str], str] = {}
    results: list[Result] = []
    for index, op in enumerate(compiled.plan.operations):
        result = run(_resolve(op, bindings), engine, version=version)
        results.append(result)
        if result.created_id is not None:
            bindings[index] = result.created_id
        for part, sub in result.created_subids.items():
            bindings[index, part] = sub
        if on_event is not None:
            for event in events_for(op, result):
                on_event(event)
        for step in compiled.host_after.get(index, ()):
            _run_host_sync(step)
    if on_event is not None:
        on_event(WorkspaceBuilt(bindings.get(0, "")))
    return PlanResult(tuple(results), bindings)


async def abuild_workspace(
    ws: Workspace,
    engine: AsyncTmuxEngine,
    *,
    version: str | None = None,
    preflight: bool = True,
    on_event: Callable[[BuildEvent], Awaitable[None]] | None = None,
) -> PlanResult:
    """Compile and execute *ws* asynchronously over *engine* (same resolution).

    *on_event* is awaited for each build event, so an async observer can stream
    the structural progress (e.g. through a fastmcp Context).
    """
    if preflight and await _preflight_async(ws, engine, version):
        return PlanResult((), {})
    compiled = compile_full(ws, version=version)
    for step in compiled.pre:
        await _run_host_async(step)
    bindings: dict[int | tuple[int, str], str] = {}
    results: list[Result] = []
    for index, op in enumerate(compiled.plan.operations):
        result = await arun(_resolve(op, bindings), engine, version=version)
        results.append(result)
        if result.created_id is not None:
            bindings[index] = result.created_id
        for part, sub in result.created_subids.items():
            bindings[index, part] = sub
        if on_event is not None:
            for event in events_for(op, result):
                await on_event(event)
        for step in compiled.host_after.get(index, ()):
            await _run_host_async(step)
    if on_event is not None:
        await on_event(WorkspaceBuilt(bindings.get(0, "")))
    return PlanResult(tuple(results), bindings)
