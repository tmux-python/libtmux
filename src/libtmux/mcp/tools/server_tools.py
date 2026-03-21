"""MCP tools for tmux server operations."""

from __future__ import annotations

import json
import typing as t

from libtmux.mcp._utils import (
    _apply_filters,
    _get_server,
    _invalidate_server,
    _serialize_session,
    handle_tool_errors,
)

if t.TYPE_CHECKING:
    from fastmcp import FastMCP


@handle_tool_errors
def list_sessions(
    socket_name: str | None = None,
    filters: dict[str, str] | str | None = None,
) -> str:
    """List all tmux sessions.

    Parameters
    ----------
    socket_name : str, optional
        tmux socket name. Defaults to LIBTMUX_SOCKET env var.
    filters : dict or str, optional
        Django-style filters as a dict (e.g. ``{"session_name__contains": "dev"}``)
        or as a JSON string. Some MCP clients require the string form.

    Returns
    -------
    str
        JSON array of session objects.
    """
    server = _get_server(socket_name=socket_name)
    sessions = server.sessions
    return json.dumps(_apply_filters(sessions, filters, _serialize_session))


@handle_tool_errors
def create_session(
    session_name: str | None = None,
    window_name: str | None = None,
    start_directory: str | None = None,
    x: int | None = None,
    y: int | None = None,
    environment: dict[str, str] | None = None,
    socket_name: str | None = None,
) -> str:
    """Create a new tmux session.

    Parameters
    ----------
    session_name : str, optional
        Name for the new session.
    window_name : str, optional
        Name for the initial window.
    start_directory : str, optional
        Working directory for the session.
    x : int, optional
        Width of the initial window.
    y : int, optional
        Height of the initial window.
    environment : dict, optional
        Environment variables to set.
    socket_name : str, optional
        tmux socket name. Defaults to LIBTMUX_SOCKET env var.

    Returns
    -------
    str
        JSON object of the created session.
    """
    server = _get_server(socket_name=socket_name)
    kwargs: dict[str, t.Any] = {}
    if session_name is not None:
        kwargs["session_name"] = session_name
    if window_name is not None:
        kwargs["window_name"] = window_name
    if start_directory is not None:
        kwargs["start_directory"] = start_directory
    if x is not None:
        kwargs["x"] = x
    if y is not None:
        kwargs["y"] = y
    if environment is not None:
        kwargs["environment"] = environment
    session = server.new_session(**kwargs)
    return json.dumps(_serialize_session(session))


@handle_tool_errors
def kill_server(socket_name: str | None = None) -> str:
    """Kill the tmux server and all its sessions.

    Parameters
    ----------
    socket_name : str, optional
        tmux socket name. Defaults to LIBTMUX_SOCKET env var.

    Returns
    -------
    str
        Confirmation message.
    """
    server = _get_server(socket_name=socket_name)
    server.kill()
    _invalidate_server(socket_name=socket_name)
    return "Server killed successfully"


@handle_tool_errors
def get_server_info(socket_name: str | None = None) -> str:
    """Get information about the tmux server.

    Parameters
    ----------
    socket_name : str, optional
        tmux socket name. Defaults to LIBTMUX_SOCKET env var.

    Returns
    -------
    str
        JSON object with server info.
    """
    server = _get_server(socket_name=socket_name)
    alive = server.is_alive()
    info: dict[str, t.Any] = {
        "is_alive": alive,
        "socket_name": server.socket_name,
        "socket_path": str(server.socket_path) if server.socket_path else None,
        "session_count": len(server.sessions) if alive else 0,
    }
    try:
        result = server.cmd("display-message", "-p", "#{version}")
        info["version"] = result.stdout[0] if result.stdout else None
    except Exception:
        info["version"] = None
    return json.dumps(info)


def register(mcp: FastMCP) -> None:
    """Register server-level tools with the MCP instance."""
    _RO = {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    mcp.tool(title="List Sessions", annotations=_RO)(list_sessions)
    mcp.tool(
        title="Create Session",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )(create_session)
    mcp.tool(
        title="Kill Server",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )(kill_server)
    mcp.tool(title="Get Server Info", annotations=_RO)(get_server_info)
