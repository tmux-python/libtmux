"""Tests for an asyncio facade over deferred command plans."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest
from typing_extensions import assert_type

from . import async_deferred_plan_api as api, deferred_plan_api as sync_api
from .shared import Arg


@dataclass
class _FakeResult:
    """Small command result for async deferred-plan runner tests."""

    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)
    returncode: int = 0


@dataclass
class _AsyncFakeRunner:
    """Async runner that exposes a snapshot and records tmux dispatches."""

    snapshot_value: sync_api.TmuxSnapshot
    calls: list[tuple[str, tuple[Arg, ...], str | int | None]] = field(
        default_factory=list,
    )
    snapshot_calls: int = 0

    async def snapshot(self) -> sync_api.TmuxSnapshot:
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


def _snapshot() -> sync_api.TmuxSnapshot:
    return sync_api.TmuxSnapshot(
        panes=(
            sync_api.PaneRef(
                pane_id=sync_api.PaneTarget("%2"),
                window_id=sync_api.WindowTarget("@1"),
                session_id=sync_api.SessionTarget("$0"),
                pane_index=2,
                active=True,
                title="shell",
            ),
            sync_api.PaneRef(
                pane_id=sync_api.PaneTarget("%1"),
                window_id=sync_api.WindowTarget("@1"),
                session_id=sync_api.SessionTarget("$0"),
                pane_index=1,
                active=True,
                title="editor",
            ),
            sync_api.PaneRef(
                pane_id=sync_api.PaneTarget("%3"),
                window_id=sync_api.WindowTarget("@2"),
                session_id=sync_api.SessionTarget("$0"),
                pane_index=3,
                active=False,
                title="logs",
            ),
        ),
    )


def test_async_to_sequence_awaits_snapshot_without_dispatching() -> None:
    """Async plan inspection preserves the pure command assertion workflow."""

    async def scenario() -> None:
        runner = _AsyncFakeRunner(_snapshot())
        plan = (
            api.panes()
            .filter(active=True)
            .order_by("pane_index")
            .each(
                lambda pane: [
                    pane.cmd.send_keys("clear", enter=True),
                    pane.window.select_layout("even-horizontal"),
                ],
            )
        )

        sequence = await plan.to_sequence(runner)

        assert_type(plan, api.CommandPlan[None])
        assert_type(sequence, api.CommandSequence)
        assert sequence.argvs() == (
            ("send-keys", "-t", "%1", "clear", "Enter"),
            ("select-layout", "-t", "@1", "even-horizontal"),
            ("send-keys", "-t", "%2", "clear", "Enter"),
            ("select-layout", "-t", "@1", "even-horizontal"),
        )
        assert runner.snapshot_calls == 1
        assert runner.calls == []

    asyncio.run(scenario())


def test_async_run_dispatches_one_native_tmux_sequence() -> None:
    """Async execution still batches concrete commands into one tmux call."""

    async def scenario() -> None:
        runner = _AsyncFakeRunner(_snapshot())
        plan = (
            api.panes()
            .filter(active=True)
            .order_by("pane_index")
            .each(lambda pane: pane.cmd.resize_pane(height=20))
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

    asyncio.run(scenario())


def test_async_map_and_first_are_data_only() -> None:
    """Async row transforms stay separate from command construction."""

    async def scenario() -> None:
        runner = _AsyncFakeRunner(_snapshot())
        query = api.panes().filter(active=True).order_by("pane_index")

        titles = await query.map(lambda pane: pane.title).all(runner)
        first = await query.first(runner)

        assert_type(titles, list[str])
        assert_type(first, sync_api.PaneRef | None)
        assert titles == ["editor", "shell"]
        assert first == _snapshot().panes[1]
        assert runner.calls == []

    asyncio.run(scenario())


def test_async_empty_plan_to_sequence_raises_but_run_is_noop() -> None:
    """Async empty plans match the sync no-op execution behavior."""

    async def scenario() -> None:
        runner = _AsyncFakeRunner(sync_api.TmuxSnapshot(panes=()))
        plan = api.panes().each(lambda pane: pane.cmd.resize_pane(height=20))

        with pytest.raises(api.NoCommandsResolved):
            await plan.to_sequence(runner)

        await plan.run(runner)
        assert runner.calls == []

    asyncio.run(scenario())
