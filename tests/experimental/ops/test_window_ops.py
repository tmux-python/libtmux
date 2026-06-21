"""Tests for the window mutation/navigation operations (bucket A)."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.ops import (
    LastWindow,
    LinkWindow,
    MoveWindow,
    NewWindow,
    NextWindow,
    PreviousWindow,
    ResizeWindow,
    RespawnWindow,
    RotateWindow,
    SelectWindow,
    SplitWindow,
    SwapWindow,
    UnlinkWindow,
    operation_from_dict,
    operation_to_dict,
    result_from_dict,
    result_to_dict,
    run,
)
from libtmux.experimental.ops._types import IndexRef, SessionId, WindowId

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
        test_id="select_window",
        op=SelectWindow(target=WindowId("@1")),
        expected=("select-window", "-t", "@1"),
    ),
    RenderCase(
        test_id="last_window",
        op=LastWindow(target=SessionId("$0")),
        expected=("last-window", "-t", "$0"),
    ),
    RenderCase(
        test_id="next_window",
        op=NextWindow(target=SessionId("$0")),
        expected=("next-window", "-t", "$0"),
    ),
    RenderCase(
        test_id="next_window_alert",
        op=NextWindow(target=SessionId("$0"), alert=True),
        expected=("next-window", "-t", "$0", "-a"),
    ),
    RenderCase(
        test_id="previous_window",
        op=PreviousWindow(target=SessionId("$0")),
        expected=("previous-window", "-t", "$0"),
    ),
    RenderCase(
        test_id="resize_window_width",
        op=ResizeWindow(target=WindowId("@1"), width=100),
        expected=("resize-window", "-t", "@1", "-x100"),
    ),
    RenderCase(
        test_id="rotate_window_up",
        op=RotateWindow(target=WindowId("@1"), up=True),
        expected=("rotate-window", "-t", "@1", "-U"),
    ),
    RenderCase(
        test_id="respawn_window_kill",
        op=RespawnWindow(target=WindowId("@1"), kill=True),
        expected=("respawn-window", "-t", "@1", "-k"),
    ),
    RenderCase(
        test_id="unlink_window_kill",
        op=UnlinkWindow(target=WindowId("@1"), kill=True),
        expected=("unlink-window", "-t", "@1", "-k"),
    ),
    RenderCase(
        test_id="swap_window",
        op=SwapWindow(target=WindowId("@1"), src_target=WindowId("@2")),
        expected=("swap-window", "-t", "@1", "-s", "@2"),
    ),
    RenderCase(
        test_id="move_window",
        op=MoveWindow(target=SessionId("$0"), src_target=WindowId("@2")),
        expected=("move-window", "-t", "$0", "-s", "@2"),
    ),
    RenderCase(
        test_id="link_window",
        op=LinkWindow(target=SessionId("$0"), src_target=WindowId("@2")),
        expected=("link-window", "-t", "$0", "-s", "@2"),
    ),
)


@pytest.mark.parametrize(
    list(RenderCase._fields),
    RENDER_CASES,
    ids=[c.test_id for c in RENDER_CASES],
)
def test_window_op_render(
    test_id: str,
    op: Operation[t.Any],
    expected: tuple[str, ...],
) -> None:
    """Each window op renders the exact tmux argv."""
    assert op.render() == expected


@pytest.mark.parametrize(
    list(RenderCase._fields),
    RENDER_CASES,
    ids=[c.test_id for c in RENDER_CASES],
)
def test_window_op_round_trips(
    test_id: str,
    op: Operation[t.Any],
    expected: tuple[str, ...],
) -> None:
    """Each op (incl. its src_target) and its result round-trip via dicts."""
    assert operation_from_dict(operation_to_dict(op)) == op
    result = op.build_result(returncode=0)
    assert result_from_dict(result_to_dict(result)) == result


def test_window_navigation_live(session: Session) -> None:
    """select/next/previous/last-window move the active window."""
    from libtmux.experimental.engines import SubprocessEngine

    engine = SubprocessEngine.for_server(session.server)
    sid = session.session_id
    assert sid is not None

    run(NewWindow(target=SessionId(sid)), engine).raise_for_status()
    run(NewWindow(target=SessionId(sid)), engine).raise_for_status()

    session.refresh()
    first = session.windows[0].window_id
    assert first is not None
    run(SelectWindow(target=WindowId(first)), engine).raise_for_status()
    session.refresh()
    assert session.active_window.window_id == first

    run(NextWindow(target=SessionId(sid)), engine).raise_for_status()
    session.refresh()
    assert session.active_window.window_id != first

    assert run(LastWindow(target=SessionId(sid)), engine).ok
    assert run(PreviousWindow(target=SessionId(sid)), engine).ok


def test_resize_and_rotate_live(session: Session) -> None:
    """resize-window and rotate-window succeed against a real window."""
    from libtmux.experimental.engines import SubprocessEngine

    engine = SubprocessEngine.for_server(session.server)
    window = session.active_window
    assert window.window_id is not None

    run(SplitWindow(target=WindowId(window.window_id)), engine).raise_for_status()
    assert run(ResizeWindow(target=WindowId(window.window_id), width=90), engine).ok
    assert run(RotateWindow(target=WindowId(window.window_id)), engine).ok


def test_swap_and_move_live(session: Session) -> None:
    """swap-window swaps two windows; move-window relocates one by index."""
    from libtmux.experimental.engines import SubprocessEngine

    engine = SubprocessEngine.for_server(session.server)
    sid = session.session_id
    assert sid is not None

    run(NewWindow(target=SessionId(sid)), engine).raise_for_status()
    session.refresh()
    first = session.windows[0].window_id
    second = session.windows[1].window_id
    assert first is not None and second is not None

    assert run(
        SwapWindow(target=WindowId(first), src_target=WindowId(second)),
        engine,
    ).ok
    assert run(
        MoveWindow(target=IndexRef(9, parent=sid), src_target=WindowId(first)),
        engine,
    ).ok


def test_unlink_window_live(session: Session) -> None:
    """unlink-window -k removes a window from its session."""
    from libtmux.experimental.engines import SubprocessEngine

    engine = SubprocessEngine.for_server(session.server)
    sid = session.session_id
    assert sid is not None

    created = run(NewWindow(target=SessionId(sid)), engine)
    created.raise_for_status()
    new_id = created.new_id
    assert new_id is not None

    assert run(UnlinkWindow(target=WindowId(new_id), kill=True), engine).ok
    session.refresh()
    assert session.windows.get(window_id=new_id, default=None) is None
