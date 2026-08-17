"""Tests for pluggable planners and ordered request batching.

Planners must produce the same PlanResult while differing only in step grouping
-- the property that makes them A/B-testable.
"""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.ops import (
    BatchingPlanner,
    BoundedPlanner,
    DisplayMessage,
    DisplayMessageResult,
    LazyPlan,
    PlanStep,
    RenameWindow,
    SendKeys,
    SequentialPlanner,
    SplitWindow,
)
from libtmux.experimental.ops._types import PaneId, SlotRef, WindowId
from libtmux.experimental.ops.exc import OperationError

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.experimental.engines.base import CommandRequest, CommandResult
    from libtmux.experimental.ops.operation import Operation
    from libtmux.experimental.ops.planner import Planner
    from libtmux.session import Session


class _CountingEngine:
    """Engine that counts planner-facing calls and echoes a fabricated pane id."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.batches: list[tuple[tuple[str, ...], ...]] = []
        self._pane = 0

    @property
    def planner_step_count(self) -> int:
        """Count scalar calls and each multi-request batch once."""
        batched_requests = sum(len(batch) for batch in self.batches)
        return len(self.calls) - batched_requests + len(self.batches)

    def run(self, request: CommandRequest) -> CommandResult:
        """Record argv; fabricate a pane id when an id is captured."""
        from libtmux.experimental.engines.base import CommandResult

        self.calls.append(request.args)
        stdout: tuple[str, ...] = ()
        if "-F" in request.args and "#{pane_id}" in request.args:
            self._pane += 1
            stdout = (f"%{self._pane}",)
        return CommandResult(cmd=("tmux", *request.args), stdout=stdout, returncode=0)

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Execute each request in order."""
        requests = tuple(requests)
        self.batches.append(tuple(request.args for request in requests))
        return [self.run(req) for req in requests]


class _TruthfulBatchEngine:
    """Return a distinct result for every request in one recorded batch."""

    def __init__(self) -> None:
        self.batches: list[tuple[tuple[str, ...], ...]] = []

    def run(self, request: CommandRequest) -> CommandResult:
        """Reject merged dispatch: this engine exercises the batch contract."""
        raise AssertionError

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Return success, failure, success without aborting the ordered batch."""
        from libtmux.experimental.engines.base import CommandResult

        batch = tuple(request.args for request in requests)
        self.batches.append(batch)
        return [
            CommandResult(
                cmd=("tmux", *request.args),
                stderr=("missing target",) if index == 1 else (),
                returncode=1 if index == 1 else 0,
            )
            for index, request in enumerate(requests)
        ]


class _AsyncTruthfulBatchEngine:
    """Async twin of :class:`_TruthfulBatchEngine`."""

    def __init__(self) -> None:
        self.batches: list[tuple[tuple[str, ...], ...]] = []

    async def run(self, request: CommandRequest) -> CommandResult:
        """Reject merged dispatch: this engine exercises the batch contract."""
        raise AssertionError

    async def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Return success, failure, success without aborting the ordered batch."""
        from libtmux.experimental.engines.base import CommandResult

        batch = tuple(request.args for request in requests)
        self.batches.append(batch)
        return [
            CommandResult(
                cmd=("tmux", *request.args),
                stderr=("missing target",) if index == 1 else (),
                returncode=1 if index == 1 else 0,
            )
            for index, request in enumerate(requests)
        ]


class _OutputBatchEngine:
    """Return distinct stdout for every request in one batch."""

    def run(self, request: CommandRequest) -> CommandResult:
        """Reject scalar dispatch for this batch-only test double."""
        raise AssertionError(request)

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Return one output line carrying the request's batch index."""
        from libtmux.experimental.engines.base import CommandResult

        return [
            CommandResult(
                cmd=("tmux", *request.args),
                stdout=(f"output-{index}",),
                returncode=0,
            )
            for index, request in enumerate(requests)
        ]


class _ShortBatchEngine(_OutputBatchEngine):
    """Violate the engine contract by omitting the final batch result."""

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Return one fewer result than request."""
        return super().run_batch(requests)[:-1]


class _LongAsyncBatchEngine(_AsyncTruthfulBatchEngine):
    """Violate the engine contract by appending an unrelated result."""

    async def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Return one more result than request."""
        from libtmux.experimental.engines.base import CommandResult

        results = await super().run_batch(requests)
        results.append(CommandResult(cmd=("tmux", "extra"), returncode=0))
        return results


def _independent_rename_plan(target: WindowId | None = None) -> LazyPlan:
    """Build one batchable run whose middle operation fails in test engines."""
    target = target if target is not None else WindowId("@1")
    plan = LazyPlan()
    plan.add(RenameWindow(target=target, name="first"))
    plan.add(RenameWindow(target=WindowId("@999999"), name="missing"))
    plan.add(RenameWindow(target=target, name="continued"))
    return plan


def test_batched_step_uses_one_request_per_operation() -> None:
    """A failure belongs to op 1 and does not prevent op 2 from completing."""
    engine = _TruthfulBatchEngine()

    outcome = _independent_rename_plan().execute(engine, planner=BatchingPlanner())

    assert [result.status for result in outcome.results] == [
        "complete",
        "failed",
        "complete",
    ]
    assert [result.returncode for result in outcome.results] == [0, 1, 0]
    assert len(engine.batches) == 1
    assert len(engine.batches[0]) == 3
    assert all(";" not in request for request in engine.batches[0])


def test_async_batched_step_matches_sync_per_operation_results() -> None:
    """Async batches preserve the same failure attribution and continuation."""
    sync = _independent_rename_plan().execute(
        _TruthfulBatchEngine(),
        planner=BatchingPlanner(),
    )
    async_engine = _AsyncTruthfulBatchEngine()
    async_result = asyncio.run(
        _independent_rename_plan().aexecute(
            async_engine,
            planner=BatchingPlanner(),
        ),
    )

    assert [result.status for result in async_result.results] == [
        result.status for result in sync.results
    ]
    assert [result.returncode for result in async_result.results] == [0, 1, 0]
    assert len(async_engine.batches) == 1
    assert len(async_engine.batches[0]) == 3


def test_batch_preserves_output_per_request() -> None:
    """Output-producing operations retain their own typed payloads."""
    plan = LazyPlan()
    plan.add(DisplayMessage(target=PaneId("%1"), message="first"))
    plan.add(DisplayMessage(target=PaneId("%1"), message="second"))

    outcome = plan.execute(_OutputBatchEngine(), planner=BatchingPlanner())

    assert [
        t.cast("DisplayMessageResult", result).text for result in outcome.results
    ] == ["output-0", "output-1"]


def test_batch_rejects_wrong_result_cardinality() -> None:
    """An engine cannot silently omit a result from an operation batch."""
    plan = LazyPlan()
    plan.add(SendKeys(target=PaneId("%1"), keys="a"))
    plan.add(SendKeys(target=PaneId("%1"), keys="b"))

    with pytest.raises(OperationError, match="1 results for 2 requests"):
        plan.execute(_ShortBatchEngine(), planner=BatchingPlanner())


def test_async_batch_rejects_extra_result() -> None:
    """Async execution cannot silently attribute an extra engine result."""
    plan = LazyPlan()
    plan.add(SendKeys(target=PaneId("%1"), keys="a"))
    plan.add(SendKeys(target=PaneId("%1"), keys="b"))

    with pytest.raises(OperationError, match="3 results for 2 requests"):
        asyncio.run(plan.aexecute(_LongAsyncBatchEngine(), planner=BatchingPlanner()))


def test_control_and_subprocess_batches_share_failure_semantics(
    session: Session,
) -> None:
    """Both live engines attribute the middle failure and run the final op."""
    from libtmux.experimental.engines import ControlModeEngine, SubprocessEngine

    def exercise(engine: t.Any, window_id: str) -> list[str]:
        outcome = _independent_rename_plan(WindowId(window_id)).execute(
            engine,
            planner=BatchingPlanner(),
        )
        return [result.status for result in outcome.results]

    subprocess_window = session.new_window(window_name="batch-subprocess")
    assert subprocess_window.window_id is not None
    subprocess_statuses = exercise(
        SubprocessEngine.for_server(session.server),
        subprocess_window.window_id,
    )
    subprocess_window.refresh()

    control_window = session.new_window(window_name="batch-control")
    assert control_window.window_id is not None
    with ControlModeEngine.for_server(session.server) as engine:
        control_statuses = exercise(engine, control_window.window_id)
    control_window.refresh()

    expected = ["complete", "failed", "complete"]
    assert subprocess_statuses == control_statuses == expected
    assert subprocess_window.window_name == "continued"
    assert control_window.window_name == "continued"


def test_control_and_subprocess_batches_preserve_output(session: Session) -> None:
    """Both live transports keep stdout attached to its request."""
    from libtmux.experimental.engines import ControlModeEngine, SubprocessEngine

    pane = session.active_window.active_pane
    assert pane is not None
    pane_id = pane.pane_id
    assert pane_id is not None

    def exercise(engine: t.Any) -> list[str]:
        plan = LazyPlan()
        target = PaneId(pane_id)
        plan.add(DisplayMessage(target=target, message="first"))
        plan.add(DisplayMessage(target=target, message="second"))
        result = plan.execute(engine, planner=BatchingPlanner())
        return [t.cast("DisplayMessageResult", item).text for item in result.results]

    subprocess_output = exercise(SubprocessEngine.for_server(session.server))
    with ControlModeEngine.for_server(session.server) as engine:
        control_output = exercise(engine)

    assert subprocess_output == control_output == ["first", "second"]


def _build_plan() -> LazyPlan:
    """Split a window, then batch two decorations after the id binds."""
    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SendKeys(target=pane, keys="vim", enter=True))
    plan.add(SendKeys(target=pane, keys=":w", enter=True))
    return plan


class PlannerCase(t.NamedTuple):
    """One planner and the step count it should produce for the plan."""

    test_id: str
    planner: Planner
    steps: int


PLANNER_CASES = (
    PlannerCase(test_id="sequential", planner=SequentialPlanner(), steps=3),
    PlannerCase(test_id="batching", planner=BatchingPlanner(), steps=2),
)


@pytest.mark.parametrize(
    list(PlannerCase._fields),
    PLANNER_CASES,
    ids=[c.test_id for c in PLANNER_CASES],
)
def test_planner_step_count(
    test_id: str,
    planner: Planner,
    steps: int,
) -> None:
    """Each planner produces the expected number of execution steps."""
    engine = _CountingEngine()
    _build_plan().execute(engine, planner=planner)
    assert engine.planner_step_count == steps


def test_planners_agree_on_result() -> None:
    """Different planners yield the same per-op result (status + new pane id)."""

    def outcome(planner: Planner) -> tuple[list[str], str | None]:
        result = _build_plan().execute(_CountingEngine(), planner=planner)
        first = result.results[0]
        return [r.status for r in result.results], first.created_id

    sequential = outcome(SequentialPlanner())
    assert outcome(BatchingPlanner()) == sequential
    assert sequential == (["complete", "complete", "complete"], "%1")


def test_batching_never_uses_global_mark() -> None:
    """The creator binds first and no request mutates tmux's global mark."""
    engine = _CountingEngine()
    _build_plan().execute(engine, planner=BatchingPlanner())
    assert engine.planner_step_count == 2
    assert "#{pane_id}" in engine.calls[0]
    assert all("{marked}" not in argv for argv in engine.calls)
    assert all("-m" not in argv and "-M" not in argv for argv in engine.calls)


def test_batching_groups_ready_operations() -> None:
    """A run without a dependency barrier uses one request batch."""
    plan = LazyPlan()
    plan.add(SendKeys(target=PaneId("%1"), keys="a"))
    plan.add(SendKeys(target=PaneId("%1"), keys="b"))
    engine = _CountingEngine()
    plan.execute(engine, planner=BatchingPlanner())
    assert engine.planner_step_count == 1
    assert len(engine.batches[0]) == 2
    assert all(";" not in request for request in engine.batches[0])


def _split_decorate_plan() -> list[Operation[t.Any]]:
    """Return a creator barrier followed by two batchable decorations."""
    return [
        SplitWindow(target=WindowId("@1")),
        SendKeys(target=SlotRef(0), keys="a", enter=True),
        SendKeys(target=SlotRef(0), keys="b", enter=True),
    ]


def test_bounded_planner_no_boundaries_is_identity() -> None:
    """With no boundaries, BoundedPlanner reproduces the inner planner exactly."""
    ops = _split_decorate_plan()
    inner = BatchingPlanner()
    assert BoundedPlanner(inner, frozenset()).plan(ops) == inner.plan(ops)


def test_bounded_planner_splits_chain_at_boundary() -> None:
    """A boundary breaks a request batch between the operations it separates."""
    ops = [
        SendKeys(target=PaneId("%1"), keys="a"),
        SendKeys(target=PaneId("%1"), keys="b"),
        SendKeys(target=PaneId("%1"), keys="c"),
    ]
    steps = BoundedPlanner(BatchingPlanner(), frozenset({1})).plan(ops)
    assert steps == [PlanStep((0, 1)), PlanStep((2,))]


def test_creator_is_already_a_batch_boundary() -> None:
    """A captured id binds before dependent decorations render."""
    ops = _split_decorate_plan()
    steps = BoundedPlanner(BatchingPlanner(), frozenset({0})).plan(ops)
    assert steps == [PlanStep((0,)), PlanStep((1, 2))]


def test_bounded_planner_splits_decorations() -> None:
    """A host boundary between decorations produces separate requests."""
    ops = _split_decorate_plan()
    steps = BoundedPlanner(BatchingPlanner(), frozenset({1})).plan(ops)
    assert steps == [PlanStep((0,)), PlanStep((1,)), PlanStep((2,))]


def test_bounded_planner_preserves_result() -> None:
    """Bounding a planner changes only step grouping, never the result."""
    plan = _build_plan()
    plain = plan.execute(_CountingEngine(), planner=BatchingPlanner())
    bounded = plan.execute(
        _CountingEngine(),
        planner=BoundedPlanner(BatchingPlanner(), frozenset({1})),
    )
    assert [r.argv for r in plain.results] == [r.argv for r in bounded.results]
    assert plain.bindings == bounded.bindings
    # The boundary forced an extra planner step without changing the outcome.
    plain_calls = _CountingEngine()
    bounded_calls = _CountingEngine()
    plan.execute(plain_calls, planner=BatchingPlanner())
    plan.execute(
        bounded_calls,
        planner=BoundedPlanner(BatchingPlanner(), frozenset({1})),
    )
    assert bounded_calls.planner_step_count > plain_calls.planner_step_count


def test_batching_creator_dependency_live(session: Session) -> None:
    """A live creator binds its id before the dependent request runs."""
    from libtmux.experimental.engines import SubprocessEngine

    server = session.server
    window = session.active_window
    assert window.window_id is not None
    engine = SubprocessEngine.for_server(server)

    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId(window.window_id)))
    plan.add(SendKeys(target=pane, keys="echo batched", enter=True))

    outcome = plan.execute(engine, planner=BatchingPlanner())

    assert outcome.ok
    new_id = outcome.results[0].created_id
    assert new_id is not None
    assert server.panes.get(pane_id=new_id) is not None
