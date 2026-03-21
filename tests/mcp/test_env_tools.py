"""Tests for libtmux MCP environment tools."""

from __future__ import annotations

import json
import typing as t

from libtmux.mcp.tools.env_tools import set_environment, show_environment

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session


def test_show_environment(mcp_server: Server, mcp_session: Session) -> None:
    """show_environment returns environment variables."""
    result = show_environment(socket_name=mcp_server.socket_name)
    data = json.loads(result)
    assert isinstance(data, dict)


def test_set_environment(mcp_server: Server, mcp_session: Session) -> None:
    """set_environment sets an environment variable."""
    result = set_environment(
        name="MCP_TEST_VAR",
        value="test_value",
        socket_name=mcp_server.socket_name,
    )
    assert result.status == "set"
    assert result.name == "MCP_TEST_VAR"


def test_set_and_show_environment(mcp_server: Server, mcp_session: Session) -> None:
    """set_environment value is readable via show_environment."""
    set_environment(
        name="MCP_ROUND_TRIP",
        value="hello",
        socket_name=mcp_server.socket_name,
    )
    result = show_environment(socket_name=mcp_server.socket_name)
    data = json.loads(result)
    assert data.get("MCP_ROUND_TRIP") == "hello"


def test_show_environment_session(mcp_server: Server, mcp_session: Session) -> None:
    """show_environment can target a specific session."""
    result = show_environment(
        session_name=mcp_session.session_name,
        socket_name=mcp_server.socket_name,
    )
    data = json.loads(result)
    assert isinstance(data, dict)
