"""Tests for deprecated libtmux Server APIs.

These tests verify that deprecated methods raise exc.DeprecatedError.
"""

from __future__ import annotations

import pytest

from libtmux import exc
from libtmux.server import Server


def test_kill_server_raises_deprecated_error(server: Server) -> None:
    """Test Server.kill_server() raises exc.DeprecatedError."""
    with pytest.raises(
        exc.DeprecatedError, match=r"Server\.kill_server\(\) was deprecated"
    ):
        server.kill_server()


def test_server_get_by_id_raises_deprecated_error(server: Server) -> None:
    """Test Server.get_by_id() raises exc.DeprecatedError."""
    with pytest.raises(
        exc.DeprecatedError, match=r"Server\.get_by_id\(\) was deprecated"
    ):
        server.get_by_id("$0")


def test_server_where_raises_deprecated_error(server: Server) -> None:
    """Test Server.where() raises exc.DeprecatedError."""
    with pytest.raises(exc.DeprecatedError, match=r"Server\.where\(\) was deprecated"):
        server.where({"session_name": "test"})


def test_server_find_where_raises_deprecated_error(server: Server) -> None:
    """Test Server.find_where() raises exc.DeprecatedError."""
    with pytest.raises(
        exc.DeprecatedError, match=r"Server\.find_where\(\) was deprecated"
    ):
        server.find_where({"session_name": "test"})


def test_server_list_sessions_raises_deprecated_error(server: Server) -> None:
    """Test Server.list_sessions() raises exc.DeprecatedError."""
    with pytest.raises(
        exc.DeprecatedError, match=r"Server\.list_sessions\(\) was deprecated"
    ):
        server.list_sessions()


def test_server_children_raises_deprecated_error(server: Server) -> None:
    """Test Server.children raises exc.DeprecatedError."""
    with pytest.raises(exc.DeprecatedError, match=r"Server\.children was deprecated"):
        _ = server.children


def test_server__sessions_raises_deprecated_error(server: Server) -> None:
    """Test Server._sessions raises exc.DeprecatedError."""
    with pytest.raises(exc.DeprecatedError, match=r"Server\._sessions was deprecated"):
        _ = server._sessions


def test_server__list_sessions_raises_deprecated_error(server: Server) -> None:
    """Test Server._list_sessions() raises exc.DeprecatedError."""
    with pytest.raises(
        exc.DeprecatedError, match=r"Server\._list_sessions\(\) was deprecated"
    ):
        server._list_sessions()


def test_server__list_windows_raises_deprecated_error(server: Server) -> None:
    """Test Server._list_windows() raises exc.DeprecatedError."""
    with pytest.raises(
        exc.DeprecatedError, match=r"Server\._list_windows\(\) was deprecated"
    ):
        server._list_windows()


def test_server__update_windows_raises_deprecated_error(server: Server) -> None:
    """Test Server._update_windows() raises exc.DeprecatedError."""
    with pytest.raises(
        exc.DeprecatedError, match=r"Server\._update_windows\(\) was deprecated"
    ):
        server._update_windows()


def test_server__list_panes_raises_deprecated_error(server: Server) -> None:
    """Test Server._list_panes() raises exc.DeprecatedError."""
    with pytest.raises(
        exc.DeprecatedError, match=r"Server\._list_panes\(\) was deprecated"
    ):
        server._list_panes()


def test_server__update_panes_raises_deprecated_error(server: Server) -> None:
    """Test Server._update_panes() raises exc.DeprecatedError."""
    with pytest.raises(
        exc.DeprecatedError, match=r"Server\._update_panes\(\) was deprecated"
    ):
        server._update_panes()
