"""Tests for libtmux TmuxRelationalObject and TmuxMappingObject."""
import logging

from libtmux.pane import Pane
from libtmux.server import Server
from libtmux.session import Session
from libtmux.test import TEST_SESSION_PREFIX, namer
from libtmux.window import Window

logger = logging.getLogger(__name__)


"""Test the :class:`TmuxRelationalObject` base class object."""


def test_find_where(server: Server, session: Session) -> None:
    """Test that find_where() retrieves single matching object."""
    # server.find_where
    for session in server.sessions:
        session_id = session.session_id
        assert session_id is not None

        assert server.sessions.get(session_id=session_id) == session
        assert isinstance(server.sessions.filter(session_id=session_id)[0], Session)

        # session.find_where
        for window in session.windows:
            window_id = window.window_id
            assert window_id is not None

            assert session.windows.get(window_id=window_id) == window
            assert isinstance(session.windows.get(window_id=window_id), Window)

            # window.find_where
            for pane in window.panes:
                pane_id = pane.pane_id
                assert pane_id is not None

                assert window.panes.get(pane_id=pane_id) == pane
                assert isinstance(window.panes.get(pane_id=pane_id), Pane)


def test_find_where_None(server: Server, session: Session) -> None:
    """.find_where returns None if no results found."""
    while True:
        nonexistent_session = TEST_SESSION_PREFIX + next(namer)

        if not server.has_session(nonexistent_session):
            break

    assert len(server.sessions.filter(session_name=nonexistent_session)) == 0


def test_find_where_multiple_infos(server: Server, session: Session) -> None:
    """.find_where returns objects with multiple attributes."""
    for session in server.sessions:
        session_id = session.session_id
        assert session_id is not None
        session_name = session.session_name
        assert session_name is not None

        find_where = server.sessions.get(
            session_id=session_id,
            session_name=session_name,
        )

        assert find_where == session
        assert isinstance(find_where, Session)

        # session.find_where
        for window in session.windows:
            window_id = window.window_id
            assert window_id is not None
            window_index = window.window_index
            assert window_index is not None

            find_window_where = session.windows.get(
                window_id=window_id,
                window_index=window_index,
            )

            assert find_window_where == window
            assert isinstance(find_window_where, Window)

            # window.find_where
            for pane in window.panes:
                pane_id = pane.pane_id
                assert pane_id is not None
                pane_tty = pane.pane_tty
                assert pane_tty is not None

                find_pane_where = window.panes.get(pane_id=pane_id, pane_tty=pane_tty)

                assert find_pane_where == pane
                assert isinstance(find_pane_where, Pane)


def test_where(server: Server, session: Session) -> None:
    """Test self.where() returns matching objects."""
    window = session.attached_window
    window.split_window()  # create second pane

    for session in server.sessions:
        session_id = session.session_id
        assert session_id is not None
        session_name = session.session_name
        assert session_name is not None

        server_sessions = server.sessions.filter(
            session_id=session_id,
            session_name=session_name,
        )

        assert len(server_sessions) == 1
        assert isinstance(server_sessions, list)
        assert server_sessions[0] == session
        assert isinstance(server_sessions[0], Session)

        # session.where
        for window in session.windows:
            window_id = window.window_id
            assert window_id is not None

            window_index = window.window_index
            assert window_index is not None

            session_windows = session.windows.filter(
                window_id=window_id,
                window_index=window_index,
            )

            assert len(session_windows) == 1
            assert isinstance(session_windows, list)
            assert session_windows[0] == window
            assert isinstance(session_windows[0], Window)

            # window.where
            for pane in window.panes:
                pane_id = pane.pane_id
                assert pane_id is not None

                pane_tty = pane.pane_tty
                assert pane_tty is not None

                window_panes = window.panes.filter(pane_id=pane_id, pane_tty=pane_tty)

                assert len(window_panes) == 1
                assert isinstance(window_panes, list)
                assert window_panes[0] == pane
                assert isinstance(window_panes[0], Pane)


def test_filter(server: Server) -> None:
    """Test self.filter() retrieves child object."""
    sess = server.new_session("test")
    window = sess.attached_window

    window.split_window()  # create second pane

    for session in server.sessions:
        session_id = session.session_id
        assert session_id is not None
        get_session_by_id = server.sessions.get(session_id=session_id)

        assert get_session_by_id == session
        assert isinstance(get_session_by_id, Session)
        assert len(server.windows.filter(window_id="$" + next(namer))) == 0

        # session.filter
        for window in session.windows:
            window_id = window.window_id
            assert window_id is not None

            get_window_by_id = session.windows.get(window_id=window_id)

            assert get_window_by_id == window
            assert isinstance(get_window_by_id, Window)

            assert len(session.windows.filter(window_id="@" + next(namer))) == 0

            # window.filter
            for pane in window.panes:
                pane_id = pane.pane_id
                assert pane_id is not None

                get_pane_by_id = window.panes.get(pane_id=pane_id)

                assert get_pane_by_id == pane
                assert isinstance(get_pane_by_id, Pane)
                assert len(window.panes.filter(pane_id="%" + next(namer))) == 0
