"""Tests for deprecated libtmux Session APIs.

These tests verify that deprecated methods raise DeprecatedError.
"""

from __future__ import annotations

import typing as t

import pytest

from libtmux.exc import DeprecatedError

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session


def test_attached_window_raises_deprecated_error(session: Session) -> None:
    """Test Session.attached_window raises DeprecatedError."""
    with pytest.raises(
        DeprecatedError, match=r"Session\.attached_window was deprecated"
    ):
        _ = session.attached_window


def test_attached_pane_raises_deprecated_error(session: Session) -> None:
    """Test Session.attached_pane raises DeprecatedError."""
    with pytest.raises(DeprecatedError, match=r"Session\.attached_pane was deprecated"):
        _ = session.attached_pane


def test_attach_session_raises_deprecated_error(session: Session) -> None:
    """Test Session.attach_session() raises DeprecatedError."""
    with pytest.raises(
        DeprecatedError, match=r"Session\.attach_session\(\) was deprecated"
    ):
        session.attach_session()


def test_kill_session_raises_deprecated_error(server: Server) -> None:
    """Test Session.kill_session() raises DeprecatedError."""
    # Create a new session to kill (so we don't kill our test session)
    new_session = server.new_session(session_name="test_kill_session", detach=True)

    with pytest.raises(
        DeprecatedError, match=r"Session\.kill_session\(\) was deprecated"
    ):
        new_session.kill_session()

    # Clean up using the new API
    new_session.kill()


def test_session_get_raises_deprecated_error(session: Session) -> None:
    """Test Session.get() raises DeprecatedError."""
    with pytest.raises(DeprecatedError, match=r"Session\.get\(\) was deprecated"):
        session.get("session_name")


def test_session_getitem_raises_deprecated_error(session: Session) -> None:
    """Test Session.__getitem__() raises DeprecatedError."""
    with pytest.raises(DeprecatedError, match=r"Session\[key\] lookup was deprecated"):
        _ = session["session_name"]


def test_session_get_by_id_raises_deprecated_error(session: Session) -> None:
    """Test Session.get_by_id() raises DeprecatedError."""
    with pytest.raises(DeprecatedError, match=r"Session\.get_by_id\(\) was deprecated"):
        session.get_by_id("@0")


def test_session_where_raises_deprecated_error(session: Session) -> None:
    """Test Session.where() raises DeprecatedError."""
    with pytest.raises(DeprecatedError, match=r"Session\.where\(\) was deprecated"):
        session.where({"window_name": "test"})


def test_session_find_where_raises_deprecated_error(session: Session) -> None:
    """Test Session.find_where() raises DeprecatedError."""
    with pytest.raises(
        DeprecatedError, match=r"Session\.find_where\(\) was deprecated"
    ):
        session.find_where({"window_name": "test"})


def test_session_list_windows_raises_deprecated_error(session: Session) -> None:
    """Test Session.list_windows() raises DeprecatedError."""
    with pytest.raises(
        DeprecatedError, match=r"Session\.list_windows\(\) was deprecated"
    ):
        session.list_windows()


def test_session_children_raises_deprecated_error(session: Session) -> None:
    """Test Session.children raises DeprecatedError."""
    with pytest.raises(DeprecatedError, match=r"Session\.children was deprecated"):
        _ = session.children


def test_session__windows_raises_deprecated_error(session: Session) -> None:
    """Test Session._windows raises DeprecatedError."""
    with pytest.raises(DeprecatedError, match=r"Session\._windows was deprecated"):
        _ = session._windows


def test_session__list_windows_raises_deprecated_error(session: Session) -> None:
    """Test Session._list_windows() raises DeprecatedError."""
    with pytest.raises(
        DeprecatedError, match=r"Session\._list_windows\(\) was deprecated"
    ):
        session._list_windows()
