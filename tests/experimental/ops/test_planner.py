"""Tests for pluggable planners and the {marked} fold.

Planners must produce the same PlanResult while differing only in dispatch
count -- the property that makes them A/B-testable.
"""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.ops import (
    BoundedPlanner,
    FoldingPlanner,
    LazyPlan,
    MarkedPlanner,
    NewPane,
    PlanStep,
    SendKeys,
    SequentialPlanner,
    SplitWindow,
)
from libtmux.experimental.ops._types import PaneId, SlotRef, WindowId

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.experimental.engines.base import CommandRequest, CommandResult
    from libtmux.experimental.ops.operation import Operation
    from libtmux.experimental.ops.planner import Planner
    from libtmux.session import Session


class _CountingEngine:
    """Engine that counts dispatches and echoes a fabricated pane id."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._pane = 0

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
        return [self.run(req) for req in requests]


def _build_plan() -> LazyPlan:
    """Split a window, then decorate the new pane (the {marked}-foldable shape)."""
    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SendKeys(target=pane, keys="vim", enter=True))
    plan.add(SendKeys(target=pane, keys=":w", enter=True))
    return plan


class PlannerCase(t.NamedTuple):
    """One planner and the dispatch count it should produce for the plan."""

    test_id: str
    planner: Planner
    dispatches: int


PLANNER_CASES = (
    PlannerCase(test_id="sequential", planner=SequentialPlanner(), dispatches=3),
    PlannerCase(test_id="folding", planner=FoldingPlanner(), dispatches=2),
    PlannerCase(test_id="marked", planner=MarkedPlanner(), dispatches=1),
)


@pytest.mark.parametrize(
    list(PlannerCase._fields),
    PLANNER_CASES,
    ids=[c.test_id for c in PLANNER_CASES],
)
def test_planner_dispatch_count(
    test_id: str,
    planner: Planner,
    dispatches: int,
) -> None:
    """Each planner produces the expected number of tmux dispatches."""
    engine = _CountingEngine()
    _build_plan().execute(engine, planner=planner)
    assert len(engine.calls) == dispatches


def test_planners_agree_on_result() -> None:
    """Different planners yield the same per-op result (status + new pane id)."""

    def outcome(planner: Planner) -> tuple[list[str], str | None]:
        result = _build_plan().execute(_CountingEngine(), planner=planner)
        first = result.results[0]
        return [r.status for r in result.results], first.created_id

    sequential = outcome(SequentialPlanner())
    assert outcome(FoldingPlanner()) == sequential
    assert outcome(MarkedPlanner()) == sequential
    assert sequential == (["complete", "complete", "complete"], "%1")


def test_marked_renders_single_dispatch() -> None:
    """The {marked} fold issues split + mark + decorates + unmark in one call."""
    engine = _CountingEngine()
    _build_plan().execute(engine, planner=MarkedPlanner())
    (argv,) = engine.calls
    assert "#{pane_id}" in argv  # split captures the new pane id
    assert "-m" in argv and "-M" in argv  # mark set then cleared
    assert "{marked}" in argv  # decorates target the marked register


def test_marked_falls_back_without_pattern() -> None:
    """A non-creator chainable run still folds (no {marked} shape required)."""
    plan = LazyPlan()
    plan.add(SendKeys(target=PaneId("%1"), keys="a"))
    plan.add(SendKeys(target=PaneId("%1"), keys="b"))
    engine = _CountingEngine()
    plan.execute(engine, planner=MarkedPlanner())
    assert len(engine.calls) == 1  # folded as a plain ; chain


class _MarkedFoldCase(t.NamedTuple):
    """A pane creator and whether its decorates should {marked}-fold."""

    test_id: str
    creator: Operation[t.Any]
    marked: bool


_MARKED_FOLD_CASES = (
    _MarkedFoldCase("split_focuses_new_pane", SplitWindow(target=WindowId("@1")), True),
    _MarkedFoldCase(
        "detached_new_pane_falls_back",
        NewPane(target=PaneId("%1"), width=80, height=15),
        False,
    ),
    _MarkedFoldCase(
        "focused_new_pane_marks",
        NewPane(target=PaneId("%1"), width=80, height=15, detach=False),
        True,
    ),
)


@pytest.mark.parametrize(
    "case",
    _MARKED_FOLD_CASES,
    ids=[c.test_id for c in _MARKED_FOLD_CASES],
)
def test_marked_fold_skips_detached_creator(case: _MarkedFoldCase) -> None:
    """A detached creator's new pane isn't focused, so {marked} can't target it."""
    plan = LazyPlan()
    pane = plan.add(case.creator)
    plan.add(SendKeys(target=pane, keys="vim", enter=True))
    steps = MarkedPlanner().plan(plan.operations)
    assert any(step.marked for step in steps) is case.marked


def _split_decorate_plan() -> list[Operation[t.Any]]:
    """Return the {marked}-foldable shape: split @1, then two pane decorates."""
    return [
        SplitWindow(target=WindowId("@1")),
        SendKeys(target=SlotRef(0), keys="a", enter=True),
        SendKeys(target=SlotRef(0), keys="b", enter=True),
    ]


def test_bounded_planner_no_boundaries_is_identity() -> None:
    """With no boundaries, BoundedPlanner reproduces the inner planner exactly."""
    ops = _split_decorate_plan()
    inner = MarkedPlanner()
    assert BoundedPlanner(inner, frozenset()).plan(ops) == inner.plan(ops)


def test_bounded_planner_splits_chain_at_boundary() -> None:
    """A boundary breaks a folded chain between the two ops it separates."""
    ops = [
        SendKeys(target=PaneId("%1"), keys="a"),
        SendKeys(target=PaneId("%1"), keys="b"),
        SendKeys(target=PaneId("%1"), keys="c"),
    ]
    steps = BoundedPlanner(FoldingPlanner(), frozenset({1})).plan(ops)
    assert steps == [PlanStep((0, 1)), PlanStep((2,))]


def test_bounded_planner_demotes_marked_at_creator_boundary() -> None:
    """A host step after the creator forbids {marked}; the creator dispatches alone."""
    ops = _split_decorate_plan()
    steps = BoundedPlanner(MarkedPlanner(), frozenset({0})).plan(ops)
    # creator alone, then the decorates as a plain ; chain -- no marked fold spans
    # the boundary (the pane id is bound before the host step runs).
    assert steps == [PlanStep((0,)), PlanStep((1, 2))]
    assert not any(step.marked for step in steps)


def test_bounded_planner_keeps_marked_first_run_between_decorates() -> None:
    """A boundary between decorates keeps creator+first marked; the rest plain."""
    ops = _split_decorate_plan()
    steps = BoundedPlanner(MarkedPlanner(), frozenset({1})).plan(ops)
    assert steps == [PlanStep((0, 1), marked=True), PlanStep((2,))]


def test_bounded_planner_preserves_result() -> None:
    """Bounding a planner changes only dispatch grouping, never the result."""
    plan = _build_plan()
    plain = plan.execute(_CountingEngine(), planner=MarkedPlanner())
    bounded = plan.execute(
        _CountingEngine(),
        planner=BoundedPlanner(MarkedPlanner(), frozenset({0})),
    )
    assert [r.argv for r in plain.results] == [r.argv for r in bounded.results]
    assert plain.bindings == bounded.bindings
    # the boundary forced an extra dispatch without changing the outcome
    plain_calls = _CountingEngine()
    bounded_calls = _CountingEngine()
    plan.execute(plain_calls, planner=MarkedPlanner())
    plan.execute(bounded_calls, planner=BoundedPlanner(MarkedPlanner(), frozenset({0})))
    assert len(bounded_calls.calls) > len(plain_calls.calls)


def test_marked_fold_live(session: Session) -> None:
    """The {marked} fold creates and decorates a real pane in one dispatch."""
    from libtmux.experimental.engines import SubprocessEngine

    server = session.server
    window = session.active_window
    assert window.window_id is not None
    engine = SubprocessEngine.for_server(server)

    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId(window.window_id)))
    plan.add(SendKeys(target=pane, keys="echo marked", enter=True))

    outcome = plan.execute(engine, planner=MarkedPlanner())

    assert outcome.ok
    new_id = outcome.results[0].created_id
    assert new_id is not None
    assert server.panes.get(pane_id=new_id) is not None
