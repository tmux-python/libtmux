"""Tests for lazy-plan composition and ordered operation batching."""

from __future__ import annotations

import typing as t

from libtmux.experimental.engines import CommandResult
from libtmux.experimental.ops import (
    BatchingPlanner,
    KillWindow,
    LazyPlan,
    OpChain,
    RenameWindow,
    SendKeys,
    SplitWindow,
)
from libtmux.experimental.ops._types import PaneId, WindowId

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.experimental.engines.base import CommandRequest


class _CountingEngine:
    """An engine that records requests and returns a canned result."""

    def __init__(self, *, returncode: int = 0, stderr: tuple[str, ...] = ()) -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[tuple[str, ...]] = []
        self.batches: list[tuple[tuple[str, ...], ...]] = []

    def run(self, request: CommandRequest) -> CommandResult:
        """Record the argv and return the canned result."""
        self.calls.append(request.args)
        return CommandResult(
            cmd=("tmux", *request.args),
            stderr=self.stderr,
            returncode=self.returncode,
        )

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Execute each request in order."""
        requests = tuple(requests)
        self.batches.append(tuple(request.args for request in requests))
        return [self.run(req) for req in requests]


def test_rshift_builds_opchain() -> None:
    """``>>`` composes operations into an ordered OpChain."""
    chain = SendKeys(target=PaneId("%1"), keys="q") >> RenameWindow(
        target=WindowId("@1"),
        name="done",
    )
    assert isinstance(chain, OpChain)
    assert [op.kind for op in chain] == ["send_keys", "rename_window"]


def test_batching_planner_submits_one_ordered_batch() -> None:
    """A run of batchable ops becomes one batch with one request per op."""
    plan = LazyPlan()
    plan.add(SendKeys(target=PaneId("%1"), keys="a"))
    plan.add(RenameWindow(target=WindowId("@1"), name="x"))
    plan.add(KillWindow(target=WindowId("@2")))
    engine = _CountingEngine()

    outcome = plan.execute(engine, planner=BatchingPlanner())

    assert len(engine.batches) == 1
    assert len(engine.batches[0]) == 3
    assert all(";" not in request for request in engine.batches[0])
    assert outcome.ok
    assert [r.status for r in outcome.results] == ["complete", "complete", "complete"]


def test_sequential_planner_uses_one_step_per_op() -> None:
    """The default planner puts each operation in its own step."""
    plan = LazyPlan()
    plan.add(SendKeys(target=PaneId("%1"), keys="a"))
    plan.add(RenameWindow(target=WindowId("@1"), name="x"))
    engine = _CountingEngine()

    plan.execute(engine)  # default planner: one step per operation

    assert len(engine.calls) == 2


def test_batch_failure_is_reported_for_every_failed_request() -> None:
    """Failures remain attached to their own operation results."""
    plan = LazyPlan()
    plan.add(SendKeys(target=PaneId("%1"), keys="a"))
    plan.add(RenameWindow(target=WindowId("@1"), name="x"))
    plan.add(KillWindow(target=WindowId("@2")))
    engine = _CountingEngine(returncode=1, stderr=("boom",))

    outcome = plan.execute(engine, planner=BatchingPlanner())

    assert [r.status for r in outcome.results] == ["failed", "failed", "failed"]
    assert not outcome.ok


def test_batch_keeps_creation_ops_separate() -> None:
    """A non-batchable creator dispatches before batchable neighbours."""
    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SendKeys(target=pane, keys="vim"))
    plan.add(RenameWindow(target=WindowId("@1"), name="x"))
    from libtmux.experimental.engines import MockEngine

    outcome = plan.execute(MockEngine(), planner=BatchingPlanner())

    assert outcome.results[1].argv[:3] == ("send-keys", "-t", "%1")
    assert outcome.ok


def test_add_chain() -> None:
    """A composed OpChain can be added to a plan in order."""
    plan = LazyPlan()
    plan.add_chain(
        SendKeys(target=PaneId("%1"), keys="q") >> KillWindow(target=WindowId("@1")),
    )
    assert [op.kind for op in plan] == ["send_keys", "kill_window"]
