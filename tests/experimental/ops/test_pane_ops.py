"""Tests for the pane mutation/creation operations (bucket A)."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.ops import (
    BreakPane,
    ClearHistory,
    JoinPane,
    LastPane,
    MovePane,
    PipePane,
    ResizePane,
    RespawnPane,
    SelectPane,
    SplitWindow,
    SwapPane,
    operation_from_dict,
    operation_to_dict,
    result_from_dict,
    result_to_dict,
    run,
)
from libtmux.experimental.ops._types import PaneId, WindowId

if t.TYPE_CHECKING:
    from libtmux.experimental.ops.operation import Operation
    from libtmux.session import Session


class RenderCase(t.NamedTuple):
    """An op and the exact argv it renders."""

    test_id: str
    op: Operation[t.Any]
    expected: tuple[str, ...]


RENDER_CASES = (
    RenderCase(
        test_id="select_pane",
        op=SelectPane(target=PaneId("%1")),
        expected=("select-pane", "-t", "%1"),
    ),
    RenderCase(
        test_id="select_pane_direction_zoom",
        op=SelectPane(target=PaneId("%2"), direction="L", zoom=True),
        expected=("select-pane", "-t", "%2", "-L", "-Z"),
    ),
    RenderCase(
        test_id="last_pane",
        op=LastPane(target=WindowId("@1")),
        expected=("last-pane", "-t", "@1"),
    ),
    RenderCase(
        test_id="resize_pane_height",
        op=ResizePane(target=PaneId("%1"), height=20),
        expected=("resize-pane", "-t", "%1", "-y20"),
    ),
    RenderCase(
        test_id="resize_pane_direction",
        op=ResizePane(target=PaneId("%1"), direction="D", adjustment=5),
        expected=("resize-pane", "-t", "%1", "-D", "5"),
    ),
    RenderCase(
        test_id="respawn_pane_kill",
        op=RespawnPane(target=PaneId("%1"), kill=True),
        expected=("respawn-pane", "-t", "%1", "-k"),
    ),
    RenderCase(
        test_id="pipe_pane",
        op=PipePane(target=PaneId("%1"), command_line="cat"),
        expected=("pipe-pane", "-t", "%1", "cat"),
    ),
    RenderCase(
        test_id="clear_history",
        op=ClearHistory(target=PaneId("%1")),
        expected=("clear-history", "-t", "%1"),
    ),
    RenderCase(
        test_id="swap_pane",
        op=SwapPane(target=PaneId("%1"), src_target=PaneId("%2")),
        expected=("swap-pane", "-t", "%1", "-s", "%2"),
    ),
    RenderCase(
        test_id="join_pane",
        op=JoinPane(target=WindowId("@1"), src_target=PaneId("%2")),
        expected=("join-pane", "-t", "@1", "-v", "-d", "-s", "%2"),
    ),
    RenderCase(
        test_id="move_pane",
        op=MovePane(target=WindowId("@1"), src_target=PaneId("%2")),
        expected=("move-pane", "-t", "@1", "-v", "-d", "-s", "%2"),
    ),
    RenderCase(
        test_id="break_pane",
        op=BreakPane(src_target=PaneId("%2"), name="logs"),
        expected=(
            "break-pane",
            "-d",
            "-n",
            "logs",
            "-P",
            "-F",
            "#{window_id}",
            "-s",
            "%2",
        ),
    ),
)


@pytest.mark.parametrize(
    list(RenderCase._fields),
    RENDER_CASES,
    ids=[c.test_id for c in RENDER_CASES],
)
def test_pane_op_render(
    test_id: str,
    op: Operation[t.Any],
    expected: tuple[str, ...],
) -> None:
    """Each pane op renders the exact tmux argv."""
    assert op.render() == expected


@pytest.mark.parametrize(
    list(RenderCase._fields),
    RENDER_CASES,
    ids=[c.test_id for c in RENDER_CASES],
)
def test_pane_op_round_trips(
    test_id: str,
    op: Operation[t.Any],
    expected: tuple[str, ...],
) -> None:
    """Each op (incl. its src_target) and its result round-trip via dicts."""
    assert operation_from_dict(operation_to_dict(op)) == op
    result = op.build_result(returncode=0, stdout=("@7",))
    assert result_from_dict(result_to_dict(result)) == result


def test_break_pane_captures_new_window_id() -> None:
    """break-pane parses the captured window id into the typed result."""
    result = BreakPane(src_target=PaneId("%2")).build_result(
        returncode=0,
        stdout=("@9",),
    )
    assert result.new_id == "@9"
    assert result.created_id == "@9"


def test_select_pane_live(session: Session) -> None:
    """select-pane makes the requested pane active."""
    from libtmux.experimental.engines import SubprocessEngine

    engine = SubprocessEngine.for_server(session.server)
    window = session.active_window
    assert window.window_id is not None
    original = session.active_pane
    assert original is not None and original.pane_id is not None

    run(SplitWindow(target=WindowId(window.window_id)), engine).raise_for_status()
    run(SelectPane(target=PaneId(original.pane_id)), engine).raise_for_status()

    window.refresh()
    active = window.active_pane
    assert active is not None
    assert active.pane_id == original.pane_id


def test_resize_and_clear_live(session: Session) -> None:
    """resize-pane and clear-history succeed against a real pane."""
    from libtmux.experimental.engines import SubprocessEngine

    engine = SubprocessEngine.for_server(session.server)
    pane = session.active_pane
    assert pane is not None and pane.pane_id is not None

    assert run(ResizePane(target=PaneId(pane.pane_id), height=10), engine).ok
    assert run(ClearHistory(target=PaneId(pane.pane_id)), engine).ok


def test_break_and_swap_live(session: Session) -> None:
    """break-pane creates a window; swap-pane swaps two real panes."""
    from libtmux.experimental.engines import SubprocessEngine

    engine = SubprocessEngine.for_server(session.server)
    window = session.active_window
    assert window.window_id is not None

    split = run(SplitWindow(target=WindowId(window.window_id)), engine)
    new_pane = split.new_pane_id
    assert new_pane is not None

    window.refresh()
    first = window.panes[0].pane_id
    assert first is not None
    assert run(SwapPane(target=PaneId(first), src_target=PaneId(new_pane)), engine).ok

    broken = run(BreakPane(src_target=PaneId(new_pane)), engine)
    assert broken.ok
    assert broken.new_id is not None
    assert session.server.windows.get(window_id=broken.new_id) is not None
