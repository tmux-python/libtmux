"""Tests for the async facade over deferred command plans."""

from __future__ import annotations

import asyncio
import typing as t
from dataclasses import dataclass, field

import pytest
from typing_extensions import assert_type

from libtmux._experimental.chain import _async as api, plan as sync_plan
from libtmux._experimental.chain._connection import AsyncSessionPlanExecutor
from libtmux._experimental.chain.ir import CommandChain

if t.TYPE_CHECKING:
    from libtmux._experimental.chain.ir import Arg
    from libtmux.session import Session

# Strict asyncio_mode: mark every coroutine test in this module explicitly.
pytestmark = pytest.mark.asyncio


@dataclass
class _FakeResult:
    """Minimal async command result."""

    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)
    returncode: int = 0


@dataclass
class _AsyncFakeRunner:
    """Async runner that exposes a snapshot and records dispatches."""

    snapshot_value: sync_plan.TmuxSnapshot
    calls: list[tuple[str, tuple[Arg, ...], str | int | None]] = field(
        default_factory=list,
    )
    snapshot_calls: int = 0

    async def snapshot(self) -> sync_plan.TmuxSnapshot:
        """Return the fixed tmux snapshot asynchronously."""
        await asyncio.sleep(0)
        self.snapshot_calls += 1
        return self.snapshot_value

    async def cmd(
        self,
        cmd: str,
        *args: Arg,
        target: str | int | None = None,
    ) -> _FakeResult:
        """Record one async command dispatch."""
        await asyncio.sleep(0)
        self.calls.append((cmd, args, target))
        return _FakeResult(stdout=["async ok"])


def _snapshot() -> sync_plan.TmuxSnapshot:
    return sync_plan.TmuxSnapshot(
        panes=(
            sync_plan.PaneRef(
                pane_id=sync_plan.PaneTarget("%2"),
                window_id=sync_plan.WindowTarget("@1"),
                session_id=sync_plan.SessionTarget("$0"),
                pane_index=2,
                active=True,
                title="shell",
            ),
            sync_plan.PaneRef(
                pane_id=sync_plan.PaneTarget("%1"),
                window_id=sync_plan.WindowTarget("@1"),
                session_id=sync_plan.SessionTarget("$0"),
                pane_index=1,
                active=True,
                title="editor",
            ),
            sync_plan.PaneRef(
                pane_id=sync_plan.PaneTarget("%3"),
                window_id=sync_plan.WindowTarget("@2"),
                session_id=sync_plan.SessionTarget("$0"),
                pane_index=3,
                active=False,
                title="logs",
            ),
        ),
    )


async def test_async_to_chain_awaits_snapshot_without_dispatching() -> None:
    """Async plan inspection preserves the pure command-assertion workflow."""
    runner = _AsyncFakeRunner(_snapshot())
    plan = (
        api.panes()
        .filter(active=True)
        .order_by("pane_index")
        .commands(
            lambda pane: [
                pane.cmd.send_keys("clear", enter=True),
                pane.window.select_layout("even-horizontal"),
            ],
        )
    )

    sequence = await plan.to_chain(runner)

    assert_type(plan, api.CommandPlan)
    assert_type(sequence, CommandChain)
    assert sequence.argvs() == (
        ("send-keys", "-t", "%1", "clear", "Enter"),
        ("select-layout", "-t", "@1", "even-horizontal"),
        ("send-keys", "-t", "%2", "clear", "Enter"),
        ("select-layout", "-t", "@1", "even-horizontal"),
    )
    assert runner.snapshot_calls == 1
    assert runner.calls == []


async def test_async_run_dispatches_one_native_tmux_sequence() -> None:
    """Async execution still chains concrete commands into one tmux call."""
    runner = _AsyncFakeRunner(_snapshot())
    plan = (
        api.panes()
        .filter(active=True)
        .order_by("pane_index")
        .commands(lambda pane: pane.cmd.resize_pane(height=20))
    )

    await plan.run(runner)

    assert runner.calls == [
        (
            "resize-pane",
            (
                "-t",
                "%1",
                "-y",
                "20",
                ";",
                "resize-pane",
                "-t",
                "%2",
                "-y",
                "20",
            ),
            None,
        ),
    ]


async def test_async_map_and_first_are_data_only() -> None:
    """Async row transforms stay separate from command construction."""
    runner = _AsyncFakeRunner(_snapshot())
    query = api.panes().filter(active=True).order_by("pane_index")

    titles = await query.map(lambda pane: pane.title).all(runner)
    first = await query.first(runner)

    assert_type(titles, list[str])
    assert titles == ["editor", "shell"]
    assert first is not None
    assert first.pane_id.value == "%1"
    assert runner.calls == []


async def test_async_empty_plan_to_chain_raises_but_run_is_noop() -> None:
    """Async empty plans match the sync no-op execution behavior."""
    runner = _AsyncFakeRunner(sync_plan.TmuxSnapshot(panes=()))
    plan = api.panes().commands(lambda pane: pane.cmd.resize_pane(height=20))

    with pytest.raises(api.NoCommandsResolved):
        await plan.to_chain(runner)

    await plan.run(runner)
    assert runner.calls == []


async def test_async_session_plan_runner_dispatches_against_live_tmux(
    session: Session,
) -> None:
    """The async live adapter resolves and dispatches against a real server."""
    session.active_window.split()
    runner = AsyncSessionPlanExecutor(session)

    snapshot = await runner.snapshot()
    assert len(snapshot.panes) >= 2

    plan = api.panes().commands(
        lambda pane: pane.cmd.send_keys("echo libtmux", enter=True),
    )
    sequence = await plan.to_chain(runner)

    # Every active and inactive pane in the snapshot is targeted.
    targeted = {argv[2] for argv in sequence.argvs()}
    assert targeted == {pane.pane_id.value for pane in snapshot.panes}

    # Dispatches once through the worker thread without raising.
    await plan.run(runner)
