"""Tests for the lazy plan and deferred-ref resolution."""

from __future__ import annotations

import asyncio
import dataclasses
import typing as t

import pytest

from libtmux.experimental.engines import AsyncMockEngine, MockEngine
from libtmux.experimental.engines.base import CommandResult
from libtmux.experimental.ops import (
    BatchingPlanner,
    BreakPane,
    DisplayMessage,
    JoinPane,
    LazyPlan,
    MovePane,
    NewSession,
    PlanStep,
    SendKeys,
    SequentialPlanner,
    SplitWindow,
    StepReport,
    SwapPane,
)
from libtmux.experimental.ops._types import NameRef, PaneId, SlotRef, WindowId
from libtmux.experimental.ops.exc import (
    FailedCreateError,
    ForwardCaptureError,
    OperationError,
)

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.experimental.engines.base import CommandRequest
    from libtmux.experimental.ops.operation import Operation


class _StaticPlanner(t.NamedTuple):
    """Planner test double returning a fixed list of steps.

    Attributes
    ----------
    steps : list[PlanStep]
        Steps returned unchanged from :meth:`plan`.
    """

    steps: list[PlanStep]

    def plan(self, operations: Sequence[Operation[t.Any]]) -> list[PlanStep]:
        """Return the configured steps without inspecting *operations*."""
        del operations
        return self.steps


class _ListClearingPlanner:
    """Malicious planner that clears mutable input when given one."""

    def plan(self, operations: Sequence[Operation[t.Any]]) -> list[PlanStep]:
        """Attempt to erase the caller's operation collection."""
        if isinstance(operations, list):
            operations.clear()
        return [PlanStep((index,)) for index in range(len(operations))]


@dataclasses.dataclass(frozen=True, kw_only=True)
class _BatchableNewSession(NewSession):
    """Test-only creator proving custom planner dependency validation."""

    batchable = True


@dataclasses.dataclass(frozen=True, kw_only=True)
class _BatchableComposite(BreakPane):
    """Test-only composite proving custom planner validation."""

    batchable = True


def test_plan_records_without_executing() -> None:
    """Building a plan touches no engine; it just records operations."""
    plan = LazyPlan()
    plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SendKeys(target=PaneId("%1"), keys="x"))
    assert len(plan) == 2
    assert [op.kind for op in plan] == ["split_window", "send_keys"]


def test_plan_resolves_forward_ref() -> None:
    """A later step can target the pane an earlier split creates."""
    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SendKeys(target=pane, keys="vim", enter=True))

    outcome = plan.execute(MockEngine())

    assert outcome.bindings == {0: "%1"}
    assert outcome.results[1].argv == (
        "send-keys",
        "-t",
        "%1",
        "--",
        "vim",
        "Enter",
    )
    assert outcome.ok


@pytest.mark.parametrize(
    "steps",
    [
        [PlanStep((1, 0))],
        [PlanStep((0, 0))],
        [PlanStep((0,))],
        [PlanStep(()), PlanStep((0, 1))],
    ],
    ids=["reordered", "duplicate", "omitted", "empty"],
)
def test_plan_rejects_invalid_partitions(steps: list[PlanStep]) -> None:
    """A custom planner must return every operation once and in order."""
    plan = LazyPlan()
    plan.add(SendKeys(target=PaneId("%1"), keys="a"))
    plan.add(SendKeys(target=PaneId("%1"), keys="b"))

    with pytest.raises(OperationError, match="exact ordered partition"):
        plan.execute(MockEngine(), planner=_StaticPlanner(steps))


def test_explain_rejects_invalid_partitions() -> None:
    """Plan explanations enforce the same planner contract as execution."""
    plan = LazyPlan()
    plan.add(SendKeys(target=PaneId("%1"), keys="a"))

    with pytest.raises(OperationError, match="exact ordered partition"):
        plan.explain(_StaticPlanner([PlanStep(())]))


def test_custom_planner_cannot_mutate_recorded_operations() -> None:
    """Planning receives an immutable snapshot, not LazyPlan's live list."""
    plan = LazyPlan()
    plan.add(SendKeys(target=PaneId("%1"), keys="a"))

    result = plan.execute(MockEngine(), planner=_ListClearingPlanner())

    assert len(plan) == 1
    assert len(result.results) == 1


def test_callback_mutation_applies_only_to_later_execution() -> None:
    """An on_step callback cannot change the operation snapshot in flight."""
    plan = LazyPlan()
    plan.add(SendKeys(target=PaneId("%1"), keys="a"))
    appended = False

    def append_once(_report: StepReport) -> None:
        nonlocal appended
        if not appended:
            plan.add(SendKeys(target=PaneId("%1"), keys="later"))
            appended = True

    first = plan.execute(MockEngine(), on_step=append_once)
    second = plan.execute(MockEngine())

    assert len(first.results) == 1
    assert len(plan) == len(second.results) == 2


def test_plan_rejects_batch_with_dependency_barrier() -> None:
    """A creator cannot share a batch with an operation needing its id."""
    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SendKeys(target=pane, keys="a"))

    with pytest.raises(OperationError, match="non-batchable operation"):
        plan.execute(MockEngine(), planner=_StaticPlanner([PlanStep((0, 1))]))


def test_plan_rejects_batchable_composite_operation() -> None:
    """A composite operation cannot silently skip its required follow-up."""
    plan = LazyPlan()
    plan.add(_BatchableComposite(src_target=PaneId("%1")))
    plan.add(SendKeys(target=PaneId("%1"), keys="a"))

    with pytest.raises(OperationError, match="composite operation 'break_pane'"):
        plan.execute(MockEngine(), planner=_StaticPlanner([PlanStep((0, 1))]))


def test_plan_rejects_same_step_slot_dependency() -> None:
    """A custom batchable creator still must bind before a dependent request."""
    plan = LazyPlan()
    session = plan.add(_BatchableNewSession(capture_panes=True))
    plan.add(SendKeys(target=session.pane, keys="a"))

    with pytest.raises(
        OperationError,
        match="operation at index 1 before slot 0 could bind",
    ):
        plan.execute(MockEngine(), planner=_StaticPlanner([PlanStep((0, 1))]))


def test_batchable_custom_creators_bind_primary_and_child_ids() -> None:
    """A valid creator batch binds every captured id before the next step."""
    plan = LazyPlan()
    plan.add(_BatchableNewSession(capture_panes=True))
    second = plan.add(_BatchableNewSession(capture_panes=True))
    plan.add(SendKeys(target=second.pane, keys="a"))

    result = plan.execute(
        MockEngine(),
        planner=_StaticPlanner([PlanStep((0, 1)), PlanStep((2,))]),
    )

    assert result.bindings == {
        0: "$1",
        (0, "window"): "@1",
        (0, "pane"): "%1",
        1: "$2",
        (1, "window"): "@2",
        (1, "pane"): "%2",
    }
    assert result.results[2].argv[:3] == ("send-keys", "-t", "%2")


def test_plan_rejects_batch_with_ensured_operation() -> None:
    """An ensure branch must resolve before another request is dispatched."""
    plan = LazyPlan()
    plan.add(SendKeys(target=PaneId("%1"), keys="a"))
    plan.add(SendKeys(target=PaneId("%1"), keys="b"))
    plan.ensure(0, DisplayMessage(target=PaneId("%1"), message="#{pane_id}"))

    with pytest.raises(OperationError, match="batched ensured operation"):
        plan.execute(MockEngine(), planner=_StaticPlanner([PlanStep((0, 1))]))


def test_plan_execute_auto_resolves_engine_version() -> None:
    """plan.execute() resolves the engine version before batched renders."""
    from libtmux.experimental.ops import BatchingPlanner, RespawnPane

    class VersionedMockEngine(MockEngine):
        def tmux_version(self) -> str | None:
            return "2.9"

    plan = LazyPlan()
    plan.add(RespawnPane(target=PaneId("%1"), environment={"E": "1"}))
    plan.add(RespawnPane(target=PaneId("%2"), environment={"E": "2"}))

    outcome = plan.execute(VersionedMockEngine(), planner=BatchingPlanner())

    # -e is gated at tmux 3.0; the engine's resolved 2.9 drops it from every
    # request in the batch.
    assert outcome.ok
    for result in outcome.results:
        assert not any(arg.startswith("-e") for arg in result.argv)


class SrcResolveCase(t.NamedTuple):
    """A dual-target op whose ``src_target`` is a forward :class:`SlotRef`."""

    test_id: str
    op: Operation[t.Any]


SRC_RESOLVE_CASES = (
    SrcResolveCase("swap_pane", SwapPane(target=PaneId("%0"), src_target=SlotRef(0))),
    SrcResolveCase("join_pane", JoinPane(target=WindowId("@0"), src_target=SlotRef(0))),
    SrcResolveCase("move_pane", MovePane(target=WindowId("@0"), src_target=SlotRef(0))),
    SrcResolveCase("break_pane", BreakPane(src_target=SlotRef(0))),
)


@pytest.mark.parametrize(
    list(SrcResolveCase._fields),
    SRC_RESOLVE_CASES,
    ids=[c.test_id for c in SRC_RESOLVE_CASES],
)
def test_plan_resolves_src_target(test_id: str, op: Operation[t.Any]) -> None:
    """A SlotRef used as ``src_target`` resolves to the captured id."""
    plan = LazyPlan()
    plan.add(SplitWindow(target=WindowId("@1")))  # slot 0 -> %1
    plan.add(op)
    outcome = plan.execute(MockEngine())
    assert outcome.ok
    assert outcome.results[1].argv[-2:] == ("-s", "%1")


class BatchedSrcCase(t.NamedTuple):
    """An operation whose two targets reference earlier bound slots."""

    test_id: str
    op: Operation[t.Any]


BATCHED_SRC_CASES = (
    BatchedSrcCase("swap_pane", SwapPane(target=SlotRef(1), src_target=SlotRef(0))),
    BatchedSrcCase("join_pane", JoinPane(target=SlotRef(1), src_target=SlotRef(0))),
    BatchedSrcCase("move_pane", MovePane(target=SlotRef(1), src_target=SlotRef(0))),
)


@pytest.mark.parametrize(
    list(BatchedSrcCase._fields),
    BATCHED_SRC_CASES,
    ids=[c.test_id for c in BATCHED_SRC_CASES],
)
def test_batching_plan_resolves_both_targets(
    test_id: str,
    op: Operation[t.Any],
) -> None:
    """Both SlotRef targets resolve before their operation dispatches."""
    plan = LazyPlan()
    plan.add(SplitWindow(target=WindowId("@1")))  # slot 0 -> %1 (own step)
    plan.add(SplitWindow(target=WindowId("@1")))  # slot 1 -> %2
    plan.add(op)
    outcome = plan.execute(MockEngine(), planner=BatchingPlanner())
    assert outcome.ok
    assert outcome.results[2].argv[-2:] == ("-s", "%1")


def test_plan_aexecute_matches_execute() -> None:
    """The async driver resolves refs identically to the sync driver."""
    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SendKeys(target=pane, keys="vim", enter=True))

    outcome = asyncio.run(plan.aexecute(AsyncMockEngine()))

    assert outcome.bindings == {0: "%1"}
    assert outcome.results[1].argv == (
        "send-keys",
        "-t",
        "%1",
        "--",
        "vim",
        "Enter",
    )


def test_plan_async_drivers_never_call_sync_version_probe() -> None:
    """aexecute() and astream() await the async version capability once each."""
    from libtmux.experimental.ops import PlanDone, RespawnPane

    class AsyncVersionedMockEngine(AsyncMockEngine):
        def __init__(self) -> None:
            super().__init__()
            self.version_calls = 0

        def tmux_version(self) -> str | None:
            raise AssertionError

        async def atmux_version(self) -> str | None:
            self.version_calls += 1
            await asyncio.sleep(0)
            return "2.9"

    plan = LazyPlan()
    plan.add(RespawnPane(target=PaneId("%1"), environment={"E": "1"}))
    plan.add(RespawnPane(target=PaneId("%2"), environment={"E": "2"}))
    engine = AsyncVersionedMockEngine()

    async def _check() -> None:
        direct = await plan.aexecute(engine, planner=BatchingPlanner())
        streamed = [event async for event in plan.astream(engine)]
        terminal = streamed[-1]
        assert isinstance(terminal, PlanDone)
        for outcome in (direct, terminal.result):
            assert outcome.ok
            for result in outcome.results:
                assert not any(arg.startswith("-e") for arg in result.argv)

    asyncio.run(_check())
    assert engine.version_calls == 2


def test_execute_on_step_reports_each_step() -> None:
    """on_step fires once per planner step, carrying its per-op results and ids."""
    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SendKeys(target=pane, keys="vim", enter=True))

    reports: list[StepReport] = []
    outcome = plan.execute(
        MockEngine(),
        planner=SequentialPlanner(),
        on_step=reports.append,
    )

    # One report per op (sequential), in planner-step order.
    assert [report.step.indices for report in reports] == [(0,), (1,)]
    # the creator's report already sees its freshly-bound pane id
    assert reports[0].bindings == {0: "%1"}
    assert reports[0].results[0].created_id == "%1"
    # the decorate report carries the resolved send-keys argv
    assert reports[1].results[0].argv == (
        "send-keys",
        "-t",
        "%1",
        "--",
        "vim",
        "Enter",
    )
    # the reported results are the same objects the PlanResult collects
    assert tuple(report.results[0] for report in reports) == outcome.results


def test_aexecute_on_step_matches_execute() -> None:
    """The async hook fires identically to the sync one (one report per step)."""
    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SendKeys(target=pane, keys="vim", enter=True))

    sync_steps: list[tuple[int, ...]] = []
    plan.execute(
        MockEngine(),
        on_step=lambda report: sync_steps.append(report.step.indices),
    )

    async_steps: list[tuple[int, ...]] = []

    async def collect(report: StepReport) -> None:
        async_steps.append(report.step.indices)

    asyncio.run(plan.aexecute(AsyncMockEngine(), on_step=collect))
    assert async_steps == sync_steps == [(0,), (1,)]


def test_step_report_bindings_cannot_mutate_plan_state() -> None:
    """A callback cannot retarget later operations through the binding snapshot."""
    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SendKeys(target=pane, keys="safe"))

    def attempt_mutation(report: StepReport) -> None:
        if 0 not in report.bindings:
            return
        mutable = t.cast("dict[int | tuple[int, str], str]", report.bindings)
        with pytest.raises(TypeError):
            mutable[0] = "%999"

    result = plan.execute(MockEngine(), on_step=attempt_mutation)

    assert result.results[1].argv[:3] == ("send-keys", "-t", "%1")


def test_step_report_bindings_are_point_in_time_snapshots() -> None:
    """An earlier report does not gain ids captured by a later step."""
    plan = LazyPlan()
    plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SplitWindow(target=WindowId("@1")))
    reports: list[StepReport] = []

    plan.execute(MockEngine(), on_step=reports.append)

    assert dict(reports[0].bindings) == {0: "%1"}
    assert dict(reports[1].bindings) == {0: "%1", 1: "%2"}


def test_plan_serialization_round_trip() -> None:
    """A plan (including its SlotRef targets) survives a list round-trip."""
    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SendKeys(target=pane, keys="x"))

    revived = LazyPlan.from_list(plan.to_list())

    assert revived.operations == plan.operations


def test_plan_unresolvable_ref_fails_closed() -> None:
    """Targeting a step that creates nothing raises a clear ForwardCaptureError."""
    plan = LazyPlan()
    typed = plan.add(SendKeys(target=PaneId("%1"), keys="x"))  # creates no id
    plan.add(SendKeys(target=typed, keys="y"))
    with pytest.raises(ForwardCaptureError, match="captured no id") as exc_info:
        plan.execute(MockEngine())
    assert exc_info.value.slot == 0  # points at the non-capturing creator
    # ForwardCaptureError stays an OperationError, so broad handlers keep working
    assert isinstance(exc_info.value, OperationError)


class _FailingCreateEngine:
    """A fake engine whose creates fail the way a vanishing tmux server does.

    Mirrors the real shape: ``returncode=1`` with tmux's message on stderr and
    no stdout, so the create captures no id.
    """

    def run(self, request: CommandRequest) -> CommandResult:
        """Fail every dispatched command with a tmux-style server error."""
        return CommandResult(
            cmd=("tmux", *request.args),
            stderr=("server exited unexpectedly",),
            returncode=1,
        )

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Run each request in order."""
        return [self.run(request) for request in requests]


def test_plan_failed_create_surfaces_the_tmux_error() -> None:
    """A failed create reports its tmux error, not an unbound forward reference.

    A create that fails captures no id, so the slot never binds. Reporting the
    reference would name the symptom and discard the cause, leaving the real
    tmux failure invisible.
    """
    plan = LazyPlan()
    session = plan.add(NewSession(session_name="dev", capture_panes=True))
    plan.add(SendKeys(target=session.pane, keys="x"))

    with pytest.raises(FailedCreateError, match="server exited unexpectedly") as info:
        plan.execute(_FailingCreateEngine())

    assert info.value.slot == 0  # points at the create that actually failed
    assert info.value.result.returncode == 1
    assert "new-session" in str(info.value)  # the failing command is named
    assert isinstance(info.value, OperationError)  # broad handlers keep working
    # It must NOT degrade into the misleading forward-reference error.
    assert not isinstance(info.value, ForwardCaptureError)


class _ExplainCase(t.NamedTuple):
    """A planner and the (kinds, reason) each execution step should carry."""

    test_id: str
    planner: t.Any
    expected: list[tuple[tuple[str, ...], str]]


def _split_then_sends() -> LazyPlan:
    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SendKeys(target=pane, keys="vim"))
    plan.add(SendKeys(target=pane, keys=":w"))
    return plan


_EXPLAIN_CASES: tuple[_ExplainCase, ...] = (
    _ExplainCase(
        "sequential_created_then_single",
        SequentialPlanner(),
        [
            (("split_window",), "creator"),
            (("send_keys",), "single"),
            (("send_keys",), "single"),
        ],
    ),
    _ExplainCase(
        "request_batch",
        BatchingPlanner(),
        [
            (("split_window",), "creator"),
            (("send_keys", "send_keys"), "batch"),
        ],
    ),
)


@pytest.mark.parametrize(
    "case",
    _EXPLAIN_CASES,
    ids=[c.test_id for c in _EXPLAIN_CASES],
)
def test_explain_annotates_step_boundaries(case: _ExplainCase) -> None:
    """explain() reports why operations share or split planner steps."""
    steps = _split_then_sends().explain(case.planner)
    assert [(e.kinds, e.reason) for e in steps] == case.expected


def test_astream_yields_step_then_plan_done() -> None:
    """astream() streams a StepDone per step and a terminal PlanDone."""
    from libtmux.experimental.ops import PlanDone, StepDone

    plan = _split_then_sends()

    async def drain() -> list[object]:
        return [event async for event in plan.astream(AsyncMockEngine())]

    events = asyncio.run(drain())
    assert [type(e).__name__ for e in events] == [
        "StepDone",
        "StepDone",
        "StepDone",
        "PlanDone",
    ]
    assert isinstance(events[-1], PlanDone)
    assert isinstance(events[0], StepDone)
    # the terminal PlanDone carries the same result aexecute() would return
    assert events[-1].result.ok


def test_astream_last_result_matches_aexecute() -> None:
    """The terminal PlanDone.result equals what aexecute() returns."""
    from libtmux.experimental.ops import PlanDone

    async def both() -> tuple[bool, bool]:
        streamed = [e async for e in _split_then_sends().astream(AsyncMockEngine())]
        direct = await _split_then_sends().aexecute(AsyncMockEngine())
        last = streamed[-1]
        assert isinstance(last, PlanDone)
        return last.result.ok, direct.ok

    stream_ok, direct_ok = asyncio.run(both())
    assert stream_ok == direct_ok


class _FindEngine:
    """A fake engine where the probe reports found-or-not and the create makes one."""

    def __init__(self, *, found: bool) -> None:
        self.found = found
        self.calls: list[tuple[str, ...]] = []

    def run(self, request: CommandRequest) -> CommandResult:
        """Answer a display-message probe, or a new-session create.

        The probe is *format-aware*: it returns only the ids the probe's format
        actually requests, so a probe that omits ``#{pane_id}`` yields no pane id
        -- mirroring real tmux, so a test cannot pass on ids the probe never asked
        for.
        """
        self.calls.append(request.args)
        cmd = ("tmux", *request.args)
        if request.args[0] == "display-message":
            if not self.found:
                return CommandResult(cmd=cmd, stderr=("no session",), returncode=1)
            fmt = request.args[-1]  # the -p <format> value
            ids = {"session_id": "$9", "window_id": "@9", "pane_id": "%9"}
            text = " ".join(v for key, v in ids.items() if f"#{{{key}}}" in fmt)
            return CommandResult(cmd=cmd, stdout=(text,), returncode=0)
        return CommandResult(cmd=cmd, stdout=("$1 @1 %1",), returncode=0)

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Run each request in order."""
        return [self.run(req) for req in requests]


class _EnsureCase(t.NamedTuple):
    """Whether the probe finds the object, and the id + create-count expected."""

    test_id: str
    found: bool
    session_id: str
    creates: int


_ENSURE_CASES: tuple[_EnsureCase, ...] = (
    _EnsureCase("found_reuses", found=True, session_id="$9", creates=0),
    _EnsureCase("absent_creates", found=False, session_id="$1", creates=1),
)


@pytest.mark.parametrize("case", _ENSURE_CASES, ids=[c.test_id for c in _ENSURE_CASES])
def test_ensure_probes_then_creates_only_if_absent(case: _EnsureCase) -> None:
    """An ensured create binds a found object's ids, or creates when absent."""
    plan = LazyPlan()
    slot = plan.add(NewSession(session_name="dev", capture_panes=True))
    # The probe renders the SAME capture format the create captures, so a found
    # session binds the same self/window/pane subrefs a created one would.
    plan.ensure(
        slot.slot,
        DisplayMessage(
            target=NameRef("dev"),
            message="#{session_id} #{window_id} #{pane_id}",
        ),
    )
    engine = _FindEngine(found=case.found)
    result = plan.execute(engine)

    assert result.ok
    assert result.bindings[0] == case.session_id
    assert result.bindings[0, "pane"].startswith("%")  # first-pane subref bound
    creates = [call for call in engine.calls if call[0] == "new-session"]
    assert len(creates) == case.creates  # created only when the probe found nothing


def test_ensure_probe_must_match_create_capture() -> None:
    """A probe that omits the pane id binds no pane subref (the format contract).

    This guards the ensure() footgun: the probe must render the create's capture
    format. A session-only probe finds the session but yields no pane id, so a
    downstream ``.pane`` forward-ref would fail closed rather than mis-bind.
    """
    plan = LazyPlan()
    slot = plan.add(NewSession(session_name="dev", capture_panes=True))
    plan.ensure(
        slot.slot, DisplayMessage(target=NameRef("dev"), message="#{session_id}")
    )

    result = plan.execute(_FindEngine(found=True))

    assert result.bindings[0] == "$9"  # the session bound
    assert (0, "pane") not in result.bindings  # but no pane id -- probe omitted it


def test_ensure_survives_serialization_round_trip() -> None:
    """to_list/from_list carry an ensured op's probe, so the conditional persists."""
    plan = LazyPlan()
    slot = plan.add(NewSession(session_name="dev", capture_panes=True))
    plan.ensure(
        slot.slot, DisplayMessage(target=NameRef("dev"), message="#{session_id}")
    )

    revived = LazyPlan.from_list(plan.to_list())

    assert revived.operations == plan.operations
    engine = _FindEngine(found=True)
    assert revived.execute(engine).bindings[0] == "$9"
    assert not [call for call in engine.calls if call[0] == "new-session"]
