"""Tests for libtmux MCP option tools."""

from __future__ import annotations

import typing as t

import pytest
from fastmcp.exceptions import ToolError

from libtmux.mcp.tools.option_tools import set_option, show_option

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session


def test_show_option(mcp_server: Server, mcp_session: Session) -> None:
    """show_option returns an OptionResult model."""
    result = show_option(
        option="base-index",
        scope="session",
        global_=True,
        socket_name=mcp_server.socket_name,
    )
    assert result.option == "base-index"
    assert result.value is not None


def test_show_option_invalid_scope(mcp_server: Server, mcp_session: Session) -> None:
    """show_option raises ToolError on invalid scope."""
    with pytest.raises(ToolError, match="Invalid scope"):
        show_option(
            option="base-index",
            scope="global",  # type: ignore[arg-type]
            socket_name=mcp_server.socket_name,
        )


def test_show_option_target_without_scope(
    mcp_server: Server, mcp_session: Session
) -> None:
    """show_option raises ToolError when target is given without scope."""
    with pytest.raises(ToolError, match="scope is required"):
        show_option(
            option="base-index",
            target="some_session",
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
    assert result.status == "set"
    assert result.option == "display-time"
