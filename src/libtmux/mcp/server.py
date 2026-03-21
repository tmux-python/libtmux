"""FastMCP server instance for libtmux.

Creates and configures the MCP server with all tools and resources.
"""

from __future__ import annotations

import os

from fastmcp import FastMCP

from libtmux.__about__ import __version__

_BASE_INSTRUCTIONS = (
    "libtmux MCP server for programmatic tmux control. "
    "tmux hierarchy: Server > Session > Window > Pane. "
    "Use pane_id (e.g. '%1') as the preferred targeting method - "
    "it is globally unique within a tmux server. "
    "Use send_keys to execute commands and capture_pane to read output. "
    "All tools accept an optional socket_name parameter for multi-server "
    "support (defaults to LIBTMUX_SOCKET env var).\n\n"
    "IMPORTANT — metadata vs content: list_windows, list_panes, and "
    "list_sessions only search metadata (names, IDs, current command). "
    "To find text that is actually visible in terminals — when users ask "
    "what panes 'contain', 'mention', 'show', or 'have' — use "
    "search_panes to search across all pane contents, or list_panes + "
    "capture_pane on each pane for manual inspection."
)


def _build_instructions() -> str:
    """Build server instructions, appending agent context if inside tmux.

    When the MCP server process runs inside a tmux pane, ``TMUX_PANE`` and
    ``TMUX`` environment variables are available. This function appends that
    context so the LLM knows which pane is its own without extra tool calls.

    Returns
    -------
    str
        Server instructions string, optionally with agent tmux context.
    """
    tmux_pane = os.environ.get("TMUX_PANE")
    if not tmux_pane:
        return _BASE_INSTRUCTIONS

    # Parse TMUX env: "/tmp/tmux-1000/default,48188,10"
    tmux_env = os.environ.get("TMUX", "")
    parts = tmux_env.split(",") if tmux_env else []
    socket_path = parts[0] if parts else None
    socket_name = socket_path.rsplit("/", 1)[-1] if socket_path else None

    context = (
        f"\n\nAgent context: This MCP server is running inside tmux pane {tmux_pane}"
    )
    if socket_name:
        context += f" (socket: {socket_name})"
    context += (
        ". Tool results annotate the caller's own pane with "
        "is_caller=true. Use this to distinguish your own pane from others."
    )
    return _BASE_INSTRUCTIONS + context


mcp = FastMCP(
    name="libtmux",
    version=__version__,
    instructions=_build_instructions(),
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
