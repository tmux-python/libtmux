"""libtmux MCP server - programmatic tmux control for AI agents."""

from __future__ import annotations


def main() -> None:
    """Entry point for the libtmux MCP server."""
    from libtmux.mcp.server import run_server

    run_server()
