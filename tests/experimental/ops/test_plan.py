"""Tests for the lazy plan and deferred-ref resolution."""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.engines import AsyncConcreteEngine, ConcreteEngine
from libtmux.experimental.ops import (
    BreakPane,
    JoinPane,
    LazyPlan,
    MarkedPlanner,
    MovePane,
    SendKeys,
    SequentialPlanner,
    SplitWindow,
    StepReport,
    SwapPane,
)
from libtmux.experimental.ops._types import PaneId, SlotRef, WindowId
from libtmux.experimental.ops.exc import ForwardCaptureError, OperationError

if t.TYPE_CHECKING:
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

    outcome = plan.execute(ConcreteEngine())

    assert outcome.bindings == {0: "%1"}
    assert outcome.results[1].argv == ("send-keys", "-t", "%1", "vim", "Enter")
    assert outcome.ok


def test_plan_execute_auto_resolves_engine_version() -> None:
    """plan.execute() resolves the engine version so folded renders are gated."""
    from libtmux.experimental.ops import FoldingPlanner, RespawnPane

    class VersionedConcreteEngine(ConcreteEngine):
        def tmux_version(self) -> str | None:
            return "2.9"

    plan = LazyPlan()
    plan.add(RespawnPane(target=PaneId("%1"), environment={"E": "1"}))
    plan.add(RespawnPane(target=PaneId("%2"), environment={"E": "2"}))

    outcome = plan.execute(VersionedConcreteEngine(), planner=FoldingPlanner())

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
    outcome = plan.execute(ConcreteEngine())
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
    outcome = plan.execute(ConcreteEngine(), planner=MarkedPlanner())
    assert outcome.ok
    assert outcome.results[2].argv[-2:] == ("-s", "%1")


def test_plan_aexecute_matches_execute() -> None:
    """The async driver resolves refs identically to the sync driver."""
    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SendKeys(target=pane, keys="vim", enter=True))

    outcome = asyncio.run(plan.aexecute(AsyncConcreteEngine()))

    assert outcome.bindings == {0: "%1"}
    assert outcome.results[1].argv == ("send-keys", "-t", "%1", "vim", "Enter")


def test_execute_on_step_reports_each_step() -> None:
    """on_step fires once per dispatched step, carrying its per-op results + ids."""
    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SendKeys(target=pane, keys="vim", enter=True))

    reports: list[StepReport] = []
    outcome = plan.execute(
        ConcreteEngine(),
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
        ConcreteEngine(),
        on_step=lambda report: sync_steps.append(report.step.indices),
    )

    async_steps: list[tuple[int, ...]] = []

    async def collect(report: StepReport) -> None:
        async_steps.append(report.step.indices)

    asyncio.run(plan.aexecute(AsyncConcreteEngine(), on_step=collect))
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
        plan.execute(ConcreteEngine())
    assert exc_info.value.slot == 0  # points at the non-capturing creator
    # ForwardCaptureError stays an OperationError, so broad handlers keep working
    assert isinstance(exc_info.value, OperationError)
