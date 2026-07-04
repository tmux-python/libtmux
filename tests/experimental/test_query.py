"""Tests for the live-pane query (``panes()``)."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.models.snapshots import PaneSnapshot
from libtmux.experimental.ops import LazyPlan, PaneId
from libtmux.experimental.query import ForwardPaneRef, PaneQuery, PaneRef, panes

if t.TYPE_CHECKING:
    from libtmux.session import Session


def _pane(pane_id: str, index: int, *, active: bool, command: str) -> PaneSnapshot:
    return PaneSnapshot.from_format(
        {
            "pane_id": pane_id,
            "pane_index": str(index),
            "pane_active": "1" if active else "0",
            "pane_current_command": command,
        },
    )


ROWS = (
    _pane("%1", 0, active=True, command="vim"),
    _pane("%2", 1, active=False, command="zsh"),
    _pane("%3", 2, active=False, command="vim"),
)


def _concrete(plan: LazyPlan) -> PaneRef:
    return PaneRef(
        plan,
        PaneId("%1"),
        snapshot=_pane("%1", 0, active=True, command="vim"),
    )


def test_split_returns_forward_handle() -> None:
    """A structural verb records a create and returns a forward handle."""
    plan = LazyPlan()
    new = _concrete(plan).split()
    assert isinstance(new, ForwardPaneRef)
    assert [op.kind for op in plan.operations] == ["split_window"]


def test_do_chains_on_the_handle() -> None:
    """do() records into the plan and returns the same handle."""
    plan = LazyPlan()
    ref = _concrete(plan)
    assert ref.do(lambda c: c.send_keys("vim")) is ref
    assert [op.kind for op in plan.operations] == ["send_keys"]


class _ReadCase(t.NamedTuple):
    """Whether a handle exposes concrete pane reads (concrete) or not (forward)."""

    test_id: str
    forward: bool


_READ_CASES: tuple[_ReadCase, ...] = (
    _ReadCase("concrete_reads", forward=False),
    _ReadCase("forward_no_reads", forward=True),
)


@pytest.mark.parametrize("case", _READ_CASES, ids=[c.test_id for c in _READ_CASES])
def test_handle_read_surface(case: _ReadCase) -> None:
    """Concrete handles expose pane reads; forward handles have none.

    The forward handle's absence of ``pane_id`` is what makes a premature read a
    *static* type error (mypy + ty), with the structural absence as its runtime
    shadow.
    """
    plan = LazyPlan()
    concrete = _concrete(plan)
    handle: object = concrete.split() if case.forward else concrete
    assert hasattr(handle, "pane_id") is (not case.forward)
    if not case.forward:
        assert concrete.pane_id == "%1"
        assert concrete.active is True


def test_panes_returns_query() -> None:
    """panes() starts an empty, immutable query."""
    assert panes() == PaneQuery()


def test_filter_active() -> None:
    """filter(active=True) keeps only the active pane."""
    assert [p.pane_id for p in panes().filter(active=True).all(ROWS)] == ["%1"]


def test_filter_lookup() -> None:
    """Filter matches snapshot attributes (QueryList lookups)."""
    result = panes().filter(current_command="vim").all(ROWS)
    assert [p.pane_id for p in result] == ["%1", "%3"]


def test_filter_floating() -> None:
    """filter(floating=True) selects floating overlays (tmux 3.7+)."""
    rows = (
        _pane("%1", 0, active=True, command="vim"),
        PaneSnapshot.from_format({"pane_id": "%9", "pane_floating_flag": "1"}),
    )
    assert [p.pane_id for p in panes().filter(floating=True).all(rows)] == ["%9"]
    assert [p.pane_id for p in panes().filter(floating=False).all(rows)] == ["%1"]


def test_order_by_and_limit() -> None:
    """order_by sorts and limit truncates."""
    result = panes().order_by("pane_index").limit(2).all(ROWS)
    assert [p.pane_id for p in result] == ["%1", "%2"]


def test_map_projection() -> None:
    """Map projects each matched snapshot."""
    ids = panes().filter(current_command="vim").map(lambda p: p.pane_id).all(ROWS)
    assert ids == ("%1", "%3")


def test_first_and_empty() -> None:
    """First returns the first row, or None when nothing matches."""
    first = panes().order_by("pane_index").first(ROWS)
    assert first is not None and first.pane_id == "%1"
    assert panes().filter(current_command="nope").first(ROWS) is None


def test_mapped_first() -> None:
    """A mapped query's first projects the first match (or None)."""
    assert panes().filter(active=True).map(lambda p: p.pane_id).first(ROWS) == "%1"
    assert panes().filter(active=False).map(lambda p: p.pane_id).first(()) is None


def test_query_is_immutable() -> None:
    """Each builder method returns a new query; the original is unchanged."""
    base = panes()
    narrowed = base.filter(active=True).order_by("pane_index").limit(1)
    assert base == PaneQuery()
    assert narrowed.lookups == {"active": True}


def test_empty_engine_source() -> None:
    """A query resolves against an engine; the in-memory engine has no panes."""
    from libtmux.experimental.engines import ConcreteEngine

    assert panes().all(ConcreteEngine()) == ()


def test_commands_to_plan_builds_one_op_per_pane() -> None:
    """commands(mapper) records each matched pane's op into a plan."""
    plan = (
        panes()
        .filter(current_command="vim")
        .commands(lambda p: p.cmd.send_keys("clear"))
        .to_plan(ROWS)
    )
    assert [op.kind for op in plan.operations] == ["send_keys", "send_keys"]
    assert plan.operations[0].render() == ("send-keys", "-t", "%1", "clear", "Enter")
    assert plan.operations[1].render() == ("send-keys", "-t", "%3", "clear", "Enter")


def test_bound_pane_commands_record_each_kind() -> None:
    """The cmd namespace records the expected operation kinds."""
    plan = (
        panes()
        .filter(active=True)
        .commands(
            lambda p: (
                p.cmd.resize(height=20),
                p.cmd.select(zoom=True),
                p.cmd.clear_history(),
            ),
        )
        .to_plan(ROWS)
    )
    assert [op.kind for op in plan.operations] == [
        "resize_pane",
        "select_pane",
        "clear_history",
    ]


def test_commands_empty_match_is_noop() -> None:
    """commands() over no matches builds an empty plan."""
    plan = (
        panes()
        .filter(current_command="nope")
        .commands(lambda p: p.cmd.send_keys("x"))
        .to_plan(ROWS)
    )
    assert list(plan.operations) == []


def test_commands_run_live(session: Session) -> None:
    """commands().run reads live panes, builds, and dispatches (folded)."""
    from libtmux.experimental.engines import SubprocessEngine
    from libtmux.experimental.ops import SplitWindow, run
    from libtmux.experimental.ops._types import WindowId

    engine = SubprocessEngine.for_server(session.server)
    window = session.active_window
    assert window.window_id is not None
    run(SplitWindow(target=WindowId(window.window_id)), engine).raise_for_status()

    result = (
        panes()
        .filter(window_id=window.window_id)
        .commands(lambda p: p.cmd.send_keys("true"))
        .run(engine)
    )
    assert result.ok


def test_panes_live_against_engine(session: Session) -> None:
    """panes() reads a live server through an engine and filters its panes."""
    from libtmux.experimental.engines import SubprocessEngine
    from libtmux.experimental.ops import SplitWindow, run
    from libtmux.experimental.ops._types import WindowId

    engine = SubprocessEngine.for_server(session.server)
    window = session.active_window
    assert window.window_id is not None
    run(SplitWindow(target=WindowId(window.window_id)), engine).raise_for_status()

    # Scope to our window (list-panes -a spans the whole server).
    window_panes = panes().filter(window_id=window.window_id).all(engine)
    assert len(window_panes) == 2
    active = panes().filter(window_id=window.window_id, active=True).all(engine)
    assert len(active) == 1
    assert active[0].active is True
