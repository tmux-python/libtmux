"""Tests for deferred query-driven command plan experiments."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field

import pytest
from typing_extensions import assert_type

from . import deferred_plan_api as api
from .shared import Arg


@dataclass
class _FakeResult:
    """Small command result for deferred-plan runner tests."""

    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)
    returncode: int = 0


@dataclass
class _FakeRunner:
    """Runner that exposes a snapshot and records tmux dispatches."""

    snapshot_value: api.TmuxSnapshot
    calls: list[tuple[str, tuple[Arg, ...], str | int | None]] = field(
        default_factory=list,
    )

    def snapshot(self) -> api.TmuxSnapshot:
        """Return the fixed tmux snapshot."""
        return self.snapshot_value

    def cmd(
        self,
        cmd: str,
        *args: Arg,
        target: str | int | None = None,
    ) -> _FakeResult:
        """Record one command dispatch."""
        self.calls.append((cmd, args, target))
        return _FakeResult(stdout=["ok"])


def _snapshot() -> api.TmuxSnapshot:
    return api.TmuxSnapshot(
        panes=(
            api.PaneRef(
                pane_id=api.PaneTarget("%2"),
                window_id=api.WindowTarget("@1"),
                session_id=api.SessionTarget("$0"),
                pane_index=2,
                active=True,
                title="shell",
            ),
            api.PaneRef(
                pane_id=api.PaneTarget("%1"),
                window_id=api.WindowTarget("@1"),
                session_id=api.SessionTarget("$0"),
                pane_index=1,
                active=True,
                title="editor",
            ),
            api.PaneRef(
                pane_id=api.PaneTarget("%3"),
                window_id=api.WindowTarget("@2"),
                session_id=api.SessionTarget("$0"),
                pane_index=3,
                active=False,
                title="logs",
            ),
        ),
    )


def test_typed_targets_and_bound_commands_render_targets() -> None:
    """Bound command namespaces keep pane and window targets typed."""
    pane = _snapshot().panes[0]

    pane_call = pane.cmd.send_keys("clear", enter=True)
    window_call = pane.window.select_layout("even-horizontal")

    assert_type(pane.pane_id, api.PaneTarget)
    assert_type(pane.window_id, api.WindowTarget)
    assert_type(pane.session_id, api.SessionTarget)
    assert pane_call.argv() == ("send-keys", "-t", "%2", "clear", "Enter")
    assert window_call.argv() == (
        "select-layout",
        "-t",
        "@1",
        "even-horizontal",
    )


def test_each_defers_mapper_until_sequence_resolution() -> None:
    """``each`` stores a plan node instead of eagerly calling the mapper."""
    mapper_calls: list[api.PaneRef] = []

    def mapper(pane: api.PaneRef) -> api.CommandValue:
        mapper_calls.append(pane)
        return pane.cmd.resize_pane(height=20)

    plan = api.panes().filter(active=True).each(mapper)

    assert_type(plan, api.CommandPlan[None])
    assert mapper_calls == []

    sequence = plan.to_sequence(_snapshot())

    assert [pane.pane_id.value for pane in mapper_calls] == ["%2", "%1"]
    assert sequence.argvs() == (
        ("resize-pane", "-t", "%2", "-y", "20"),
        ("resize-pane", "-t", "%1", "-y", "20"),
    )


def test_snapshot_sequence_filters_orders_and_flattens_commands() -> None:
    """Snapshot compilation gives pure assertions without touching tmux."""
    plan = (
        api.panes()
        .filter(active=True)
        .order_by("pane_index")
        .each(
            lambda pane: [
                pane.cmd.send_keys("clear", enter=True),
                pane.cmd.resize_pane(height=20),
            ],
        )
    )

    sequence = plan.to_sequence(_snapshot())

    assert sequence.argvs() == (
        ("send-keys", "-t", "%1", "clear", "Enter"),
        ("resize-pane", "-t", "%1", "-y", "20"),
        ("send-keys", "-t", "%2", "clear", "Enter"),
        ("resize-pane", "-t", "%2", "-y", "20"),
    )
    assert sequence.argv() == (
        "send-keys",
        "-t",
        "%1",
        "clear",
        "Enter",
        ";",
        "resize-pane",
        "-t",
        "%1",
        "-y",
        "20",
        ";",
        "send-keys",
        "-t",
        "%2",
        "clear",
        "Enter",
        ";",
        "resize-pane",
        "-t",
        "%2",
        "-y",
        "20",
    )


def test_flat_map_expands_multiple_commands_per_row() -> None:
    """``flat_map`` exposes the explicit multi-command row expansion."""
    plan = (
        api.panes()
        .filter(active=True)
        .flat_map(
            lambda pane: (
                pane.cmd.resize_pane(height=10),
                pane.window.select_layout("even-horizontal"),
            ),
        )
    )

    assert plan.to_sequence(_snapshot()).argvs() == (
        ("resize-pane", "-t", "%2", "-y", "10"),
        ("select-layout", "-t", "@1", "even-horizontal"),
        ("resize-pane", "-t", "%1", "-y", "10"),
        ("select-layout", "-t", "@1", "even-horizontal"),
    )


def test_map_transforms_rows_without_creating_commands() -> None:
    """``map`` remains data-oriented and separate from command construction."""
    query = api.panes().filter(active=True).order_by("pane_index")

    titles = query.map(lambda pane: pane.title).all(_snapshot())

    assert_type(titles, list[str])
    assert titles == ["editor", "shell"]


def test_run_resolves_live_snapshot_and_dispatches_once() -> None:
    """``run`` resolves the query and executes one native tmux sequence."""
    runner = _FakeRunner(_snapshot())
    plan = (
        api.panes()
        .filter(active=True)
        .order_by("pane_index")
        .each(
            lambda pane: pane.cmd.send_keys("clear", enter=True),
        )
    )

    plan.run(runner)

    assert runner.calls == [
        (
            "send-keys",
            (
                "-t",
                "%1",
                "clear",
                "Enter",
                ";",
                "send-keys",
                "-t",
                "%2",
                "clear",
                "Enter",
            ),
            None,
        ),
    ]


def test_to_sequence_uses_runner_snapshot_without_dispatching() -> None:
    """Resolving against a runner still keeps execution explicit."""
    runner = _FakeRunner(_snapshot())
    plan = (
        api.panes()
        .filter(active=True)
        .each(
            lambda pane: pane.cmd.resize_pane(height=12),
        )
    )

    sequence = plan.to_sequence(runner)

    assert sequence.argvs() == (
        ("resize-pane", "-t", "%2", "-y", "12"),
        ("resize-pane", "-t", "%1", "-y", "12"),
    )
    assert runner.calls == []


def test_empty_query_to_sequence_raises_but_run_is_noop() -> None:
    """Empty query plans are inspectably empty and executable as no-ops."""
    runner = _FakeRunner(api.TmuxSnapshot(panes=()))
    plan = api.panes().each(lambda pane: pane.cmd.resize_pane(height=20))

    with pytest.raises(api.NoCommandsResolved):
        plan.to_sequence(runner)

    plan.run(runner)
    assert runner.calls == []


def test_each_rejects_string_iterable_command_results() -> None:
    """String-like mapper results are not accepted as command iterables."""
    plan = api.panes().each(lambda pane: t.cast(t.Any, pane.title))

    with pytest.raises(TypeError, match="command mapper"):
        plan.to_sequence(_snapshot())
