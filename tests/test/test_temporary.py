"""Tests for libtmux's temporary test utilities."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.test.temporary import temp_session, temp_window

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session


def test_temp_session_creates_and_destroys(server: Server) -> None:
    """Test that temp_session creates and destroys a session."""
    with temp_session(server) as session:
        session_name = session.session_name
        assert session_name is not None
        assert server.has_session(session_name)

    assert session_name is not None
    assert not server.has_session(session_name)


def test_temp_session_with_name(server: Server) -> None:
    """Test temp_session with a provided session name."""
    session_name = "test_session"
    with temp_session(server, session_name=session_name) as session:
        assert session.session_name == session_name
        assert server.has_session(session_name)

    assert not server.has_session(session_name)


def test_temp_session_cleanup_on_exception(server: Server) -> None:
    """Test that temp_session cleans up even when an exception occurs."""
    test_error = RuntimeError()
    session_name = None

    with pytest.raises(RuntimeError), temp_session(server) as session:
        session_name = session.session_name
        assert session_name is not None
        assert server.has_session(session_name)
        raise test_error

    assert session_name is not None
    assert not server.has_session(session_name)


def test_temp_window_creates_and_destroys(session: Session) -> None:
    """Test that temp_window creates and destroys a window."""
    initial_windows = len(session.windows)

    with temp_window(session) as window:
        window_id = window.window_id
        assert window_id is not None
        assert len(session.windows) == initial_windows + 1
        assert any(w.window_id == window_id for w in session.windows)

    assert len(session.windows) == initial_windows
    assert window_id is not None
    assert not any(w.window_id == window_id for w in session.windows)


def test_temp_window_with_name(session: Session) -> None:
    """Test temp_window with a provided window name."""
    window_name = "test_window"
    initial_windows = len(session.windows)

    with temp_window(session, window_name=window_name) as window:
        assert window.window_name == window_name
        assert len(session.windows) == initial_windows + 1
        assert any(w.window_name == window_name for w in session.windows)

    assert len(session.windows) == initial_windows
    assert not any(w.window_name == window_name for w in session.windows)


def test_temp_window_cleanup_on_exception(session: Session) -> None:
    """Test that temp_window cleans up even when an exception occurs."""
    initial_windows = len(session.windows)
    test_error = RuntimeError()
    window_id = None

    with pytest.raises(RuntimeError), temp_window(session) as window:
        window_id = window.window_id
        assert window_id is not None
        assert len(session.windows) == initial_windows + 1
        assert any(w.window_id == window_id for w in session.windows)
        raise test_error

    assert len(session.windows) == initial_windows
    assert window_id is not None
    assert not any(w.window_id == window_id for w in session.windows)


def test_temp_session_outside_context(server: Server) -> None:
    """Test that temp_session's finally block handles a session already killed."""
    session_name = None

    with temp_session(server) as session:
        session_name = session.session_name
        assert session_name is not None
        assert server.has_session(session_name)

        # Kill the session while inside the context
        session.kill()
        assert not server.has_session(session_name)

    # The temp_session's finally block should handle gracefully
    # that the session is already gone
    assert session_name is not None
    assert not server.has_session(session_name)


def test_temp_window_outside_context(session: Session) -> None:
    """Test that temp_window's finally block handles a window already killed."""
    initial_windows = len(session.windows)
    window_id = None

    with temp_window(session) as window:
        window_id = window.window_id
        assert window_id is not None
        assert len(session.windows) == initial_windows + 1

        # Kill the window inside the context
        window.kill()
        assert len(session.windows) == initial_windows

    # The temp_window's finally block should handle gracefully
    # that the window is already gone
    assert window_id is not None
    assert len(session.windows) == initial_windows
    assert not any(w.window_id == window_id for w in session.windows)
