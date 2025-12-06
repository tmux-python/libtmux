"""Tests for deprecated libtmux TmuxRelationalObject APIs.

These tests verify that deprecated methods raise exc.DeprecatedError.
"""

from __future__ import annotations

import typing as t

import pytest

from libtmux import exc

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session


def test_server_find_where_raises_deprecated_error(server: Server) -> None:
    """Test Server.find_where() raises exc.DeprecatedError."""
    with pytest.raises(
        exc.DeprecatedError, match=r"Server\.find_where\(\) was deprecated"
    ):
        server.find_where({"session_name": "test"})


def test_session_find_where_raises_deprecated_error(session: Session) -> None:
    """Test Session.find_where() raises exc.DeprecatedError."""
    with pytest.raises(
        exc.DeprecatedError, match=r"Session\.find_where\(\) was deprecated"
    ):
        session.find_where({"window_name": "test"})


def test_window_find_where_raises_deprecated_error(session: Session) -> None:
    """Test Window.find_where() raises exc.DeprecatedError."""
    window = session.active_window
    with pytest.raises(
        exc.DeprecatedError, match=r"Window\.find_where\(\) was deprecated"
    ):
        window.find_where({"pane_id": "%0"})


def test_server_where_raises_deprecated_error(server: Server) -> None:
    """Test Server.where() raises exc.DeprecatedError."""
    with pytest.raises(exc.DeprecatedError, match=r"Server\.where\(\) was deprecated"):
        server.where({"session_name": "test"})


def test_session_where_raises_deprecated_error(session: Session) -> None:
    """Test Session.where() raises exc.DeprecatedError."""
    with pytest.raises(exc.DeprecatedError, match=r"Session\.where\(\) was deprecated"):
        session.where({"window_name": "test"})


def test_window_where_raises_deprecated_error(session: Session) -> None:
    """Test Window.where() raises exc.DeprecatedError."""
    window = session.active_window
    with pytest.raises(exc.DeprecatedError, match=r"Window\.where\(\) was deprecated"):
        window.where({"pane_id": "%0"})


def test_server_get_by_id_raises_deprecated_error(server: Server) -> None:
    """Test Server.get_by_id() raises exc.DeprecatedError."""
    with pytest.raises(
        exc.DeprecatedError, match=r"Server\.get_by_id\(\) was deprecated"
    ):
        server.get_by_id("$0")


def test_session_get_by_id_raises_deprecated_error(session: Session) -> None:
    """Test Session.get_by_id() raises exc.DeprecatedError."""
    with pytest.raises(
        exc.DeprecatedError, match=r"Session\.get_by_id\(\) was deprecated"
    ):
        session.get_by_id("@0")


def test_window_get_by_id_raises_deprecated_error(session: Session) -> None:
    """Test Window.get_by_id() raises exc.DeprecatedError."""
    window = session.active_window
    with pytest.raises(
        exc.DeprecatedError, match=r"Window\.get_by_id\(\) was deprecated"
    ):
        window.get_by_id("%0")
