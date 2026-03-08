"""MCP tool registration for libtmux."""

from __future__ import annotations

import typing as t

if t.TYPE_CHECKING:
    from fastmcp import FastMCP


def register_tools(mcp: FastMCP) -> None:
    """Register all tool modules with the FastMCP instance."""
    from libtmux.mcp.tools import (
        env_tools,
        option_tools,
        pane_tools,
        server_tools,
        session_tools,
        window_tools,
    )

    server_tools.register(mcp)
    session_tools.register(mcp)
    window_tools.register(mcp)
    pane_tools.register(mcp)
    option_tools.register(mcp)
    env_tools.register(mcp)
