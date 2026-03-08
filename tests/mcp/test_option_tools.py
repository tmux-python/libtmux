"""Tests for libtmux MCP option tools."""

from __future__ import annotations

import json
import typing as t

import pytest
from fastmcp.exceptions import ToolError

from libtmux.mcp.tools.option_tools import set_option, show_option

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session


def test_show_option(mcp_server: Server, mcp_session: Session) -> None:
    """show_option returns an option value."""
    result = show_option(
        option="base-index",
        scope="session",
        global_=True,
        socket_name=mcp_server.socket_name,
    )
    data = json.loads(result)
    assert data["option"] == "base-index"
    assert "value" in data


def test_show_option_invalid_scope(mcp_server: Server, mcp_session: Session) -> None:
    """show_option raises ToolError on invalid scope."""
    with pytest.raises(ToolError, match="Invalid scope"):
        show_option(
            option="base-index",
            scope="global",
            socket_name=mcp_server.socket_name,
        )


def test_set_option(mcp_server: Server, mcp_session: Session) -> None:
    """set_option sets a tmux option."""
    result = set_option(
        option="display-time",
        value="3000",
        scope="server",
        global_=True,
        socket_name=mcp_server.socket_name,
    )
    data = json.loads(result)
    assert data["status"] == "set"
    assert data["option"] == "display-time"
