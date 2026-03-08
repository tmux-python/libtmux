"""Tests for libtmux MCP server tools."""

from __future__ import annotations

import json
import typing as t

import pytest

from libtmux.mcp.tools.server_tools import (
    create_session,
    get_server_info,
    kill_server,
    list_sessions,
)

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session


def test_list_sessions(mcp_server: Server, mcp_session: Session) -> None:
    """list_sessions returns JSON array of sessions."""
    result = list_sessions(socket_name=mcp_server.socket_name)
    data = json.loads(result)
    assert isinstance(data, list)
    assert len(data) >= 1
    session_ids = [s["session_id"] for s in data]
    assert mcp_session.session_id in session_ids


def test_list_sessions_empty_server(mcp_server: Server) -> None:
    """list_sessions returns empty array when no sessions."""
    # Kill all sessions first
    for s in mcp_server.sessions:
        s.kill()
    result = list_sessions(socket_name=mcp_server.socket_name)
    data = json.loads(result)
    assert data == []


def test_create_session(mcp_server: Server) -> None:
    """create_session creates a new tmux session."""
    result = create_session(
        session_name="mcp_test_new",
        socket_name=mcp_server.socket_name,
    )
    data = json.loads(result)
    assert data["session_name"] == "mcp_test_new"
    assert data["session_id"] is not None


def test_create_session_duplicate(mcp_server: Server, mcp_session: Session) -> None:
    """create_session raises error for duplicate session name."""
    from fastmcp.exceptions import ToolError

    with pytest.raises(ToolError):
        create_session(
            session_name=mcp_session.session_name,
            socket_name=mcp_server.socket_name,
        )


def test_get_server_info(mcp_server: Server, mcp_session: Session) -> None:
    """get_server_info returns server status."""
    result = get_server_info(socket_name=mcp_server.socket_name)
    data = json.loads(result)
    assert data["is_alive"] is True
    assert data["session_count"] >= 1


def test_kill_server(mcp_server: Server, mcp_session: Session) -> None:
    """kill_server kills the tmux server."""
    result = kill_server(socket_name=mcp_server.socket_name)
    assert "killed" in result.lower()
