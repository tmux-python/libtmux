"""Tests for the lazy plan and deferred-ref resolution."""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.engines import AsyncMockEngine, MockEngine
from libtmux.experimental.engines.base import CommandResult
from libtmux.experimental.ops import (
    BreakPane,
    DisplayMessage,
    JoinPane,
    LazyPlan,
    MarkedPlanner,
    MovePane,
    NewSession,
    SendKeys,
    SequentialPlanner,
    SplitWindow,
    StepReport,
    SwapPane,
)
from libtmux.experimental.ops._types import NameRef, PaneId, SlotRef, WindowId
from libtmux.experimental.ops.exc import ForwardCaptureError, OperationError

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.experimental.engines.base import CommandRequest
    from libtmux.experimental.ops.operation import Operation


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
    assert outcome.results[1].argv == ("send-keys", "-t", "%1", "vim", "Enter")
    assert outcome.ok


def test_plan_execute_auto_resolves_engine_version() -> None:
    """plan.execute() resolves the engine version so folded renders are gated."""
    from libtmux.experimental.ops import FoldingPlanner, RespawnPane

    class VersionedMockEngine(MockEngine):
        def tmux_version(self) -> str | None:
            return "2.9"

    plan = LazyPlan()
    plan.add(RespawnPane(target=PaneId("%1"), environment={"E": "1"}))
    plan.add(RespawnPane(target=PaneId("%2"), environment={"E": "2"}))

    outcome = plan.execute(VersionedMockEngine(), planner=FoldingPlanner())

    # -e is gated at tmux 3.0; on the engine's resolved 2.9 it is dropped even
    # from the folded (rendered-in-_drive) dispatch.
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


class MarkedSrcCase(t.NamedTuple):
    """A {marked} decorate whose ``src_target`` references an earlier bound slot."""

    test_id: str
    op: Operation[t.Any]


MARKED_SRC_CASES = (
    MarkedSrcCase("swap_pane", SwapPane(target=SlotRef(1), src_target=SlotRef(0))),
    MarkedSrcCase("join_pane", JoinPane(target=SlotRef(1), src_target=SlotRef(0))),
    MarkedSrcCase("move_pane", MovePane(target=SlotRef(1), src_target=SlotRef(0))),
)


@pytest.mark.parametrize(
    list(MarkedSrcCase._fields),
    MARKED_SRC_CASES,
    ids=[c.test_id for c in MARKED_SRC_CASES],
)
def test_marked_plan_resolves_decorate_src_target(
    test_id: str,
    op: Operation[t.Any],
) -> None:
    """A {marked} decorate's ``src_target`` SlotRef resolves to the bound id."""
    plan = LazyPlan()
    plan.add(SplitWindow(target=WindowId("@1")))  # slot 0 -> %1 (own dispatch)
    plan.add(SplitWindow(target=WindowId("@1")))  # slot 1 -> the marked-fold creator
    plan.add(op)  # slot 2 -> decorate: target {marked}, src_target -> slot 0
    outcome = plan.execute(MockEngine(), planner=MarkedPlanner())
    assert outcome.ok
    assert outcome.results[2].argv[-2:] == ("-s", "%1")


def test_plan_aexecute_matches_execute() -> None:
    """The async driver resolves refs identically to the sync driver."""
    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SendKeys(target=pane, keys="vim", enter=True))

    outcome = asyncio.run(plan.aexecute(AsyncMockEngine()))

    assert outcome.bindings == {0: "%1"}
    assert outcome.results[1].argv == ("send-keys", "-t", "%1", "vim", "Enter")


def test_execute_on_step_reports_each_step() -> None:
    """on_step fires once per dispatched step, carrying its per-op results + ids."""
    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SendKeys(target=pane, keys="vim", enter=True))

    reports: list[StepReport] = []
    outcome = plan.execute(
        MockEngine(),
        planner=SequentialPlanner(),
        on_step=reports.append,
    )

    # one report per op (sequential), in dispatch order
    assert [report.step.indices for report in reports] == [(0,), (1,)]
    # the creator's report already sees its freshly-bound pane id
    assert reports[0].bindings == {0: "%1"}
    assert reports[0].results[0].created_id == "%1"
    # the decorate report carries the resolved send-keys argv
    assert reports[1].results[0].argv == ("send-keys", "-t", "%1", "vim", "Enter")
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


class _ExplainCase(t.NamedTuple):
    """A planner and the (kinds, reason) each of its dispatch steps should carry."""

    test_id: str
    planner: t.Any
    expected: list[tuple[tuple[str, ...], str]]


def _split_then_send() -> LazyPlan:
    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SendKeys(target=pane, keys="vim"))
    return plan


_EXPLAIN_CASES: tuple[_ExplainCase, ...] = (
    _ExplainCase(
        "sequential_created_then_single",
        SequentialPlanner(),
        [(("split_window",), "created-id"), (("send_keys",), "single")],
    ),
    _ExplainCase(
        "marked_fold",
        MarkedPlanner(),
        [(("split_window", "send_keys"), "marked-fold")],
    ),
)


@pytest.mark.parametrize(
    "case",
    _EXPLAIN_CASES,
    ids=[c.test_id for c in _EXPLAIN_CASES],
)
def test_explain_annotates_dispatch_boundaries(case: _ExplainCase) -> None:
    """explain() reports why each step is its own dispatch under a planner."""
    steps = _split_then_send().explain(case.planner)
    assert [(e.kinds, e.reason) for e in steps] == case.expected


def test_astream_yields_step_then_plan_done() -> None:
    """astream() streams a StepDone per step and a terminal PlanDone."""
    from libtmux.experimental.ops import PlanDone, StepDone

    plan = _split_then_send()

    async def drain() -> list[object]:
        return [event async for event in plan.astream(AsyncMockEngine())]

    events = asyncio.run(drain())
    assert [type(e).__name__ for e in events] == ["StepDone", "StepDone", "PlanDone"]
    assert isinstance(events[-1], PlanDone)
    assert isinstance(events[0], StepDone)
    # the terminal PlanDone carries the same result aexecute() would return
    assert events[-1].result.ok


def test_astream_last_result_matches_aexecute() -> None:
    """The terminal PlanDone.result equals what aexecute() returns."""
    from libtmux.experimental.ops import PlanDone

    async def both() -> tuple[bool, bool]:
        streamed = [e async for e in _split_then_send().astream(AsyncMockEngine())]
        direct = await _split_then_send().aexecute(AsyncMockEngine())
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
