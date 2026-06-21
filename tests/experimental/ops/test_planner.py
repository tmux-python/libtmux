"""Tests for pluggable planners and the {marked} fold.

Planners must produce the same PlanResult while differing only in dispatch
count -- the property that makes them A/B-testable.
"""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.ops import (
    FoldingPlanner,
    LazyPlan,
    MarkedPlanner,
    SendKeys,
    SequentialPlanner,
    SplitWindow,
)
from libtmux.experimental.ops._types import PaneId, WindowId

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.experimental.engines.base import CommandRequest, CommandResult
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
