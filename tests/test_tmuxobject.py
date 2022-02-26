"""Test for tmuxp TmuxRelationalObject and TmuxMappingObject."""
import logging

from libtmux import Pane, Session, Window
from libtmux.test import TEST_SESSION_PREFIX, namer

logger = logging.getLogger(__name__)


"""Test the :class:`TmuxRelationalObject` base class object."""


def test_find_where(server, session):
    """Test that find_where() retrieves single matching object."""
    # server.find_where
    for session in server.sessions:
        session_id = session.get("session_id")

        assert server.find_where({"session_id": session_id}) == session
        assert isinstance(server.find_where({"session_id": session_id}), Session)

        # session.find_where
        for window in session.windows:
            window_id = window.get("window_id")

            assert session.find_where({"window_id": window_id}) == window
            assert isinstance(session.find_where({"window_id": window_id}), Window)

            # window.find_where
            for pane in window.panes:
                pane_id = pane.get("pane_id")

                assert window.find_where({"pane_id": pane_id}) == pane
                assert isinstance(window.find_where({"pane_id": pane_id}), Pane)


def test_find_where_None(server, session):
    """.find_where returns None if no results found."""

    while True:
        nonexistant_session = TEST_SESSION_PREFIX + next(namer)

        if not server.has_session(nonexistant_session):
            break

    assert server.find_where({"session_name": nonexistant_session}) is None


def test_find_where_multiple_infos(server, session):
    """.find_where returns objects with multiple attributes."""

    for session in server.sessions:
        session_id = session.get("session_id")
        session_name = session.get("session_name")
        find_where = server.find_where(
            {"session_id": session_id, "session_name": session_name}
        )

        assert find_where == session
        assert isinstance(find_where, Session)

        # session.find_where
        for window in session.windows:
            window_id = window.get("window_id")
            window_index = window.get("window_index")

            find_where = session.find_where(
                {"window_id": window_id, "window_index": window_index}
            )

            assert find_where == window
            assert isinstance(find_where, Window)

            # window.find_where
            for pane in window.panes:
                pane_id = pane.get("pane_id")
                pane_tty = pane.get("pane_tty")

                find_where = window.find_where(
                    {"pane_id": pane_id, "pane_tty": pane_tty}
                )

                assert find_where == pane
                assert isinstance(find_where, Pane)


def test_where(server, session):
    """Test self.where() returns matching objects."""

    window = session.attached_window
    window.split_window()  # create second pane

    for session in server.sessions:
        session_id = session.get("session_id")
        session_name = session.get("session_name")
        where = server.where({"session_id": session_id, "session_name": session_name})

        assert len(where) == 1
        assert isinstance(where, list)
        assert where[0] == session
        assert isinstance(where[0], Session)

        # session.where
        for window in session.windows:
            window_id = window.get("window_id")
            window_index = window.get("window_index")

            where = session.where(
                {"window_id": window_id, "window_index": window_index}
            )

            assert len(where) == 1
            assert isinstance(where, list)
            assert where[0] == window
            assert isinstance(where[0], Window)

            # window.where
            for pane in window.panes:
                pane_id = pane.get("pane_id")
                pane_tty = pane.get("pane_tty")

                where = window.where({"pane_id": pane_id, "pane_tty": pane_tty})

                assert len(where) == 1
                assert isinstance(where, list)
                assert where[0] == pane
                assert isinstance(where[0], Pane)


def test_get_by_id(server, session):
    """Test self.get_by_id() retrieves child object."""

    window = session.attached_window

    window.split_window()  # create second pane

    for session in server.sessions:
        session_id = session.get("session_id")
        get_by_id = server.get_by_id(session_id)

        assert get_by_id == session
        assert isinstance(get_by_id, Session)
        assert server.get_by_id("$" + next(namer)) is None

        # session.get_by_id
        for window in session.windows:
            window_id = window.get("window_id")

            get_by_id = session.get_by_id(window_id)

            assert get_by_id == window
            assert isinstance(get_by_id, Window)

            assert session.get_by_id("@" + next(namer)) is None

            # window.get_by_id
            for pane in window.panes:
                pane_id = pane.get("pane_id")

                get_by_id = window.get_by_id(pane_id)

                assert get_by_id == pane
                assert isinstance(get_by_id, Pane)
                assert window.get_by_id("%" + next(namer)) is None
