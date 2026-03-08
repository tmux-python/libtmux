"""Tests for libtmux MCP session tools."""

from __future__ import annotations

import json
import typing as t

from libtmux.mcp.tools.session_tools import (
    create_window,
    kill_session,
    list_windows,
    rename_session,
)

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session


def test_list_windows(mcp_server: Server, mcp_session: Session) -> None:
    """list_windows returns JSON array of windows."""
    result = list_windows(
        session_name=mcp_session.session_name,
        socket_name=mcp_server.socket_name,
    )
    data = json.loads(result)
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "window_id" in data[0]


def test_list_windows_by_id(mcp_server: Server, mcp_session: Session) -> None:
    """list_windows can find session by ID."""
    result = list_windows(
        session_id=mcp_session.session_id,
        socket_name=mcp_server.socket_name,
    )
    data = json.loads(result)
    assert len(data) >= 1


def test_create_window(mcp_server: Server, mcp_session: Session) -> None:
    """create_window creates a new window in a session."""
    result = create_window(
        session_name=mcp_session.session_name,
        window_name="mcp_test_win",
        socket_name=mcp_server.socket_name,
    )
    data = json.loads(result)
    assert data["window_name"] == "mcp_test_win"


def test_rename_session(mcp_server: Server, mcp_session: Session) -> None:
    """rename_session renames an existing session."""
    original_name = mcp_session.session_name
    result = rename_session(
        new_name="mcp_renamed",
        session_name=original_name,
        socket_name=mcp_server.socket_name,
    )
    data = json.loads(result)
    assert data["session_name"] == "mcp_renamed"


def test_kill_session(mcp_server: Server) -> None:
    """kill_session kills a session."""
    mcp_server.new_session(session_name="mcp_kill_me")
    result = kill_session(
        session_name="mcp_kill_me",
        socket_name=mcp_server.socket_name,
    )
    assert "killed" in result.lower()
    assert not mcp_server.has_session("mcp_kill_me")
