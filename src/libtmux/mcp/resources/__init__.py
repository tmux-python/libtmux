"""MCP resource registration for libtmux."""

from __future__ import annotations

import typing as t

if t.TYPE_CHECKING:
    from fastmcp import FastMCP


def register_resources(mcp: FastMCP) -> None:
    """Register all resource modules with the FastMCP instance."""
    from libtmux.mcp.resources import hierarchy

    hierarchy.register(mcp)
