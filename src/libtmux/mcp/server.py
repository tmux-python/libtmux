"""FastMCP server instance for libtmux.

Creates and configures the MCP server with all tools and resources.
"""

from __future__ import annotations

from fastmcp import FastMCP

from libtmux.__about__ import __version__

mcp = FastMCP(
    name="libtmux",
    version=__version__,
    instructions=(
        "libtmux MCP server for programmatic tmux control. "
        "tmux hierarchy: Server > Session > Window > Pane. "
        "Use pane_id (e.g. '%1') as the preferred targeting method - "
        "it is globally unique within a tmux server. "
        "Use send_keys to execute commands and capture_pane to read output. "
        "All tools accept an optional socket_name parameter for multi-server "
        "support (defaults to LIBTMUX_SOCKET env var)."
    ),
)


def _register_all() -> None:
    """Register all tools and resources with the MCP server."""
    from libtmux.mcp.resources import register_resources
    from libtmux.mcp.tools import register_tools

    register_tools(mcp)
    register_resources(mcp)


def run_server() -> None:
    """Run the MCP server."""
    _register_all()
    mcp.run()
