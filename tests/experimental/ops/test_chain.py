"""Tests for lazy-plan chainability (>> composition and ; folding)."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.engines import CommandResult
from libtmux.experimental.ops import (
    CapturePane,
    FoldingPlanner,
    KillWindow,
    LazyPlan,
    OpChain,
    RenameWindow,
    SendKeys,
    SplitWindow,
)
from libtmux.experimental.ops._chain import (
    attribute_marked,
    ensure_chainable,
    render_chain,
)
from libtmux.experimental.ops._types import PaneId, WindowId
from libtmux.experimental.ops.exc import OperationError

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.experimental.engines.base import CommandRequest


class _CountingEngine:
    """An engine that counts dispatches and returns a canned result."""

    def __init__(self, *, returncode: int = 0, stderr: tuple[str, ...] = ()) -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[tuple[str, ...]] = []

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
        return [self.run(req) for req in requests]


def test_rshift_builds_opchain() -> None:
    """``>>`` composes operations into an ordered OpChain."""
    chain = SendKeys(target=PaneId("%1"), keys="q") >> RenameWindow(
        target=WindowId("@1"),
        name="done",
    )
    assert isinstance(chain, OpChain)
    assert [op.kind for op in chain] == ["send_keys", "rename_window"]


def test_ensure_chainable_rejects_output_ops() -> None:
    """Output/creation ops are not chainable (fail closed)."""
    ensure_chainable(SendKeys(target=PaneId("%1"), keys="q"))  # ok
    with pytest.raises(OperationError, match="not chainable"):
        ensure_chainable(CapturePane(target=PaneId("%1")))
    with pytest.raises(OperationError, match="not chainable"):
        ensure_chainable(SplitWindow(target=WindowId("@1")))


def test_render_chain_joins_with_separator() -> None:
    """Chainable ops render to one argv with standalone ';' separators."""
    argv = render_chain(
        [
            SendKeys(target=PaneId("%1"), keys="vim", enter=True),
            RenameWindow(target=WindowId("@1"), name="edit"),
        ],
    )
    assert argv == (
        "send-keys",
        "-t",
        "%1",
        "vim",
        "Enter",
        ";",
        "rename-window",
        "-t",
        "@1",
        "edit",
    )


def test_fold_dispatches_once() -> None:
    """A run of chainable ops folds into a single engine dispatch."""
    plan = LazyPlan()
    plan.add(SendKeys(target=PaneId("%1"), keys="a"))
    plan.add(RenameWindow(target=WindowId("@1"), name="x"))
    plan.add(KillWindow(target=WindowId("@2")))
    engine = _CountingEngine()

    outcome = plan.execute(engine, planner=FoldingPlanner())

    assert len(engine.calls) == 1  # all three folded into one ';' dispatch
    assert ";" in engine.calls[0]
    assert outcome.ok
    assert [r.status for r in outcome.results] == ["complete", "complete", "complete"]


def test_no_fold_dispatches_per_op() -> None:
    """Without folding, each op dispatches on its own (default behaviour)."""
    plan = LazyPlan()
    plan.add(SendKeys(target=PaneId("%1"), keys="a"))
    plan.add(RenameWindow(target=WindowId("@1"), name="x"))
    engine = _CountingEngine()

    plan.execute(engine)  # fold defaults to False

    assert len(engine.calls) == 2


def test_fold_failure_attributes_first_failed_rest_skipped() -> None:
    """A folded failure marks the first op failed and the rest skipped."""
    plan = LazyPlan()
    plan.add(SendKeys(target=PaneId("%1"), keys="a"))
    plan.add(RenameWindow(target=WindowId("@1"), name="x"))
    plan.add(KillWindow(target=WindowId("@2")))
    engine = _CountingEngine(returncode=1, stderr=("boom",))

    outcome = plan.execute(engine, planner=FoldingPlanner())

    assert [r.status for r in outcome.results] == ["failed", "skipped", "skipped"]
    assert not outcome.ok


def test_fold_keeps_creation_ops_unfolded() -> None:
    """A non-chainable creator dispatches alone; chainable neighbours fold."""
    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId("@1")))  # not chainable
    plan.add(SendKeys(target=pane, keys="vim"))  # chainable, targets new pane
    plan.add(RenameWindow(target=WindowId("@1"), name="x"))  # chainable
    from libtmux.experimental.engines import ConcreteEngine

    outcome = plan.execute(ConcreteEngine(), planner=FoldingPlanner())

    # split resolved the pane id; the send-keys folded with rename, retargeted
    assert outcome.results[1].argv[:3] == ("send-keys", "-t", "%1")
    assert outcome.ok


class MarkedAttrCase(t.NamedTuple):
    """A merged {marked} dispatch result and the per-op statuses it yields."""

    test_id: str
    merged: CommandResult
    new_id: str | None
    create_status: str
    decorate_statuses: list[str]


_MARK_CREATE = SplitWindow(target=WindowId("@1"))
_MARK_DECORATES = (
    SendKeys(target=PaneId("%9"), keys="a"),
    SendKeys(target=PaneId("%9"), keys="b"),
)

MARKED_ATTR_CASES = (
    MarkedAttrCase(
        test_id="all_succeed",
        merged=CommandResult(cmd=("tmux",), stdout=("%2",), returncode=0),
        new_id="%2",
        create_status="complete",
        decorate_statuses=["complete", "complete"],
    ),
    MarkedAttrCase(
        test_id="create_fails",
        merged=CommandResult(cmd=("tmux",), returncode=1, stderr=("boom",)),
        new_id=None,
        create_status="failed",
        decorate_statuses=["skipped", "skipped"],
    ),
    MarkedAttrCase(
        test_id="capture_false_success",
        merged=CommandResult(cmd=("tmux",), returncode=0),
        new_id=None,
        create_status="complete",
        decorate_statuses=["complete", "complete"],
    ),
    MarkedAttrCase(
        test_id="decorate_fails",
        merged=CommandResult(
            cmd=("tmux",), stdout=("%2",), returncode=1, stderr=("x",)
        ),
        new_id="%2",
        create_status="complete",
        decorate_statuses=["failed", "skipped"],
    ),
)


@pytest.mark.parametrize(
    list(MarkedAttrCase._fields),
    MARKED_ATTR_CASES,
    ids=[c.test_id for c in MARKED_ATTR_CASES],
)
def test_attribute_marked(
    test_id: str,
    merged: CommandResult,
    new_id: str | None,
    create_status: str,
    decorate_statuses: list[str],
) -> None:
    """A failed create skips all decorates; a failed decorate blames the first."""
    created, decorated, got_id = attribute_marked(_MARK_CREATE, _MARK_DECORATES, merged)
    assert got_id == new_id
    assert created.status == create_status
    assert [r.status for r in decorated] == decorate_statuses


def test_attribute_marked_decorate_target_is_concrete_pane() -> None:
    """Decorate results address the concrete new pane, not {marked} (for replay)."""
    merged = CommandResult(cmd=("tmux",), stdout=("%2",), returncode=0)
    _created, decorated, _new_id = attribute_marked(
        _MARK_CREATE,
        _MARK_DECORATES,
        merged,
    )
    assert all(r.operation.target == PaneId("%2") for r in decorated)


def test_attribute_marked_failed_decorate_drops_create_stdout() -> None:
    """A failed decorate is not credited with the create's captured pane id."""
    merged = CommandResult(
        cmd=("tmux",), stdout=("%2",), returncode=1, stderr=("boom",)
    )
    _created, decorated, _new_id = attribute_marked(
        _MARK_CREATE,
        _MARK_DECORATES,
        merged,
    )
    assert decorated[0].status == "failed"
    assert "%2" not in decorated[0].stdout


def test_attribute_marked_blank_stdout_is_no_id() -> None:
    """A whitespace-only captured id is treated as no id (never bound as '')."""
    merged = CommandResult(cmd=("tmux",), stdout=("   ",), returncode=0)
    _created, _decorated, new_id = attribute_marked(
        _MARK_CREATE,
        _MARK_DECORATES,
        merged,
    )
    assert new_id is None


def test_add_chain() -> None:
    """A composed OpChain can be added to a plan in order."""
    plan = LazyPlan()
    plan.add_chain(
        SendKeys(target=PaneId("%1"), keys="q") >> KillWindow(target=WindowId("@1")),
    )
    assert [op.kind for op in plan] == ["send_keys", "kill_window"]
