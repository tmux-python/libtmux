"""MCP tools for tmux server operations."""

from __future__ import annotations

import typing as t

from libtmux.mcp._utils import (
    ANNOTATIONS_CREATE,
    ANNOTATIONS_DESTRUCTIVE,
    ANNOTATIONS_RO,
    TAG_DESTRUCTIVE,
    TAG_MUTATING,
    TAG_READONLY,
    _apply_filters,
    _get_server,
    _invalidate_server,
    _serialize_session,
    handle_tool_errors,
)
from libtmux.mcp.models import ServerInfo, SessionInfo

if t.TYPE_CHECKING:
    from fastmcp import FastMCP


@handle_tool_errors
def list_sessions(
    socket_name: str | None = None,
    filters: dict[str, str] | str | None = None,
) -> list[SessionInfo]:
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
    list[SessionInfo]
        List of session objects.
    """
    server = _get_server(socket_name=socket_name)
    sessions = server.sessions
    return _apply_filters(sessions, filters, _serialize_session)


@handle_tool_errors
def create_session(
    session_name: str | None = None,
    window_name: str | None = None,
    start_directory: str | None = None,
    x: int | None = None,
    y: int | None = None,
    environment: dict[str, str] | None = None,
    socket_name: str | None = None,
) -> SessionInfo:
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
    SessionInfo
        The created session.
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
    return _serialize_session(session)


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
def get_server_info(socket_name: str | None = None) -> ServerInfo:
    """Get information about the tmux server.

    Parameters
    ----------
    socket_name : str, optional
        tmux socket name. Defaults to LIBTMUX_SOCKET env var.

    Returns
    -------
    ServerInfo
        Server information.
    """
    server = _get_server(socket_name=socket_name)
    alive = server.is_alive()
    version: str | None = None
    try:
        result = server.cmd("display-message", "-p", "#{version}")
        version = result.stdout[0] if result.stdout else None
    except Exception:
        pass
    return ServerInfo(
        is_alive=alive,
        socket_name=server.socket_name,
        socket_path=str(server.socket_path) if server.socket_path else None,
        session_count=len(server.sessions) if alive else 0,
        version=version,
    )


def register(mcp: FastMCP) -> None:
    """Register server-level tools with the MCP instance."""
    mcp.tool(title="List Sessions", annotations=ANNOTATIONS_RO, tags={TAG_READONLY})(
        list_sessions
    )
    mcp.tool(
        title="Create Session", annotations=ANNOTATIONS_CREATE, tags={TAG_MUTATING}
    )(create_session)
    mcp.tool(
        title="Kill Server", annotations=ANNOTATIONS_DESTRUCTIVE, tags={TAG_DESTRUCTIVE}
    )(kill_server)
    mcp.tool(title="Get Server Info", annotations=ANNOTATIONS_RO, tags={TAG_READONLY})(
        get_server_info
    )
