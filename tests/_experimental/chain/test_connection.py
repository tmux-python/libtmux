"""Live-tmux integration tests for the chain connection layer."""

from __future__ import annotations

import typing as t

from libtmux._experimental.chain._connection import (
    SessionPlanExecutor,
    snapshot_from_session,
)
from libtmux._experimental.chain.plan import PaneTarget, panes

if t.TYPE_CHECKING:
    from libtmux.session import Session


def test_snapshot_from_session_reads_live_panes(session: Session) -> None:
    """A snapshot reflects the session's real panes with typed targets."""
    session.active_window.split()

    snapshot = snapshot_from_session(session)

    assert len(snapshot.panes) >= 2
    for pane in snapshot.panes:
        assert isinstance(pane.pane_id, PaneTarget)
        assert pane.pane_id.value.startswith("%")
        assert pane.window_id.value.startswith("@")
        assert pane.session_id.value.startswith("$")


def test_session_plan_runner_compiles_real_targets(session: Session) -> None:
    """A plan resolved through the runner targets the session's real panes."""
    session.active_window.split()
    runner = SessionPlanExecutor(session)
    snapshot = runner.snapshot()

    plan = panes().commands(lambda pane: pane.cmd.send_keys("echo cc", enter=True))
    sequence = plan.to_chain(runner)

    # Every compiled command targets a real pane id from the live snapshot.
    targeted = {argv[2] for argv in sequence.argvs()}
    assert targeted == {pane.pane_id.value for pane in snapshot.panes}


def test_session_plan_runner_dispatches_plan_once(session: Session) -> None:
    """Running a plan dispatches against the live server without error."""
    session.active_window.split()
    runner = SessionPlanExecutor(session)

    plan = (
        panes()
        .filter(active=True)
        .commands(
            lambda pane: pane.cmd.send_keys("echo libtmux", enter=True),
        )
    )

    # Resolves the live snapshot and dispatches as one native tmux invocation.
    # ``run`` returns ``None``; this asserts the dispatch raises nothing.
    plan.run(runner)


def test_empty_plan_run_is_noop_against_live_session(session: Session) -> None:
    """A plan that resolves to no commands is a live no-op."""
    runner = SessionPlanExecutor(session)

    # ``limit(0)`` yields no rows, so the plan resolves to no commands.
    plan = (
        panes().limit(0).commands(lambda pane: pane.cmd.send_keys("echo x", enter=True))
    )

    # No commands resolved -> a silent no-op (does not raise).
    plan.run(runner)
