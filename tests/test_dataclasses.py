"""Tests for libtmux object model, querying and traversal, etc."""

from __future__ import annotations

import typing as t

import pytest

from libtmux._internal.query_list import (
    MultipleObjectsReturned,
    ObjectDoesNotExist,
    QueryList,
)
from libtmux.constants import ResizeAdjustmentDirection
from libtmux.pane import Pane
from libtmux.session import Session
from libtmux.window import Window

if t.TYPE_CHECKING:
    import pathlib

    from libtmux.server import Server

    ListCmd = t.Literal["list-sessions", "list-windows", "list-panes"]
    ListExtraArgs = tuple[str] | None


OutputRaw = dict[str, t.Any]
OutputsRaw = list[OutputRaw]


def test_pane(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    server: Server,
) -> None:
    """Verify Pane dataclass object."""
    monkeypatch.chdir(tmp_path)

    try:
        session_ = server.sessions[0]
    except Exception:
        session_ = server.new_session()

    assert session_ is not None

    window_ = session_.active_window
    window_.split()
    pane_ = window_.split()
    window_.select_layout("main-vertical")

    assert pane_ is not None
    assert pane_.pane_id is not None

    assert isinstance(pane_.pane_id, str)

    pane = Pane.from_pane_id(server=pane_.server, pane_id=pane_.pane_id)

    assert isinstance(pane, Pane)

    #
    # Refreshing
    #
    pane.refresh()

    old_pane_size = pane.pane_height

    pane.resize(adjustment_direction=ResizeAdjustmentDirection.Down, adjustment=25)
    pane.resize(
        adjustment_direction=ResizeAdjustmentDirection.Right,
        adjustment=25,
    )

    assert old_pane_size != pane.pane_height
    assert pane.pane_current_command is not None

    #
    # Relations
    #
    assert pane.window is not None
    assert isinstance(pane.window, Window)

    assert pane.window.session is not None
    assert isinstance(pane.window.session, Session)

    assert pane.session is not None
    assert isinstance(pane.session, Session)

    #
    # Relations: Child objects
    #
    assert isinstance(pane, Pane)
    assert isinstance(pane.session, Session)

    # Session
    assert pane.session.windows
    assert isinstance(pane.session.windows, list)
    assert len(pane.session.windows) > 0
    for w in pane.session.windows:
        assert isinstance(w, Window)
        assert isinstance(w.session, Session)
        assert w.session_id == pane.session.session_id

    assert len(pane.session.panes) > 0
    for _p in pane.session.panes:
        assert isinstance(_p, Pane)
        assert isinstance(_p.session, Session)
        assert _p.session_id == pane.session.session_id

    # Session -> QueryList
    assert len(pane.window.panes) > 0
    session = pane.session
    window = session.new_window(window_name="test")
    assert len(session.windows) > 1
    for _w in session.windows.filter(window_name=window.window_name):
        assert isinstance(_w, Window)
        assert isinstance(_w.session, Session)
        assert _w.window_name == window.window_name

    # Window
    assert len(pane.session.panes) > 0
    assert len(window.panes) > 0
    for _p in window.panes:
        assert isinstance(_p, Pane)
        assert isinstance(_p.session, Session)
        assert _p.window_id == window.window_id

    #
    # Split window
    #

    # Window-level
    new_pane = window.split()
    assert new_pane.pane_id != pane.pane_id
    assert new_pane.window_id == window.window_id

    # Pane-level
    new_pane_2 = new_pane.split()
    assert new_pane_2.pane_id != new_pane.pane_id
    assert new_pane_2.window_id == new_pane.window_id


@pytest.fixture
def session(session: Session) -> Session:
    """Verify creating Session with Session.from_session_id()."""
    assert session.session_id is not None
    return Session.from_session_id(server=session.server, session_id=session.session_id)


def test_querylist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    session: Session,
) -> None:
    """Verify QueryList behavior with libtmux object."""
    monkeypatch.chdir(tmp_path)

    session.new_window(window_name="test_2")
    session.new_window(window_name="test_3")

    qs = QueryList(session.windows)

    assert qs.count(session.windows[0]) == 1
    assert len(qs) == 3

    for w in qs.filter():
        assert isinstance(w, Window)

    for w in qs.filter(window_name="test_2"):
        assert isinstance(w, Window)
        assert w.window_name == "test_2"

    w_2 = qs.get(window_name="test_2")
    assert isinstance(w_2, Window)
    assert w_2.window_name == "test_2"

    with pytest.raises(ObjectDoesNotExist):
        qs.get(window_name="non_existent")

    result = qs.get(window_name="non_existent", default="default_value")
    assert result == "default_value"

    # Test for multiple objects
    server = session.server
    second_session = server.new_session("second session")
    second_session.new_window(window_name="test_2")
    assert len(server.windows.filter(window_name="test_2")) == 2
    with pytest.raises(MultipleObjectsReturned):
        server.windows.get(window_name="test_2")
