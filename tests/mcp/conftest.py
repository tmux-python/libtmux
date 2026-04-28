"""Test fixtures for libtmux MCP server tests."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.mcp._utils import _server_cache

if t.TYPE_CHECKING:
    from libtmux.pane import Pane
    from libtmux.server import Server
    from libtmux.session import Session
    from libtmux.window import Window


@pytest.fixture(autouse=True)
def _clear_server_cache() -> t.Generator[None, None, None]:
    """Clear the MCP server cache between tests."""
    _server_cache.clear()
    yield
    _server_cache.clear()


@pytest.fixture
def mcp_server(server: Server) -> Server:
    """Provide a libtmux Server pre-registered in the MCP cache.

    This fixture sets up the server cache so MCP tools can find the
    test server without environment variables.
    """
    cache_key = (server.socket_name, None, None)
    _server_cache[cache_key] = server
    # Also register as default for tools that don't specify a socket
    _server_cache[(None, None, None)] = server
    return server


@pytest.fixture
def mcp_session(mcp_server: Server, session: Session) -> Session:
    """Provide a session accessible via MCP tools."""
    return session


@pytest.fixture
def mcp_window(mcp_session: Session) -> Window:
    """Provide a window accessible via MCP tools."""
    return mcp_session.active_window


@pytest.fixture
def mcp_pane(mcp_window: Window) -> Pane:
    """Provide a pane accessible via MCP tools."""
    active_pane = mcp_window.active_pane
    assert active_pane is not None
    return active_pane
