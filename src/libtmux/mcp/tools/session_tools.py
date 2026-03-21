"""MCP tools for tmux session operations."""

from __future__ import annotations

import typing as t

from libtmux.constants import WindowDirection
from libtmux.mcp._utils import (
    _apply_filters,
    _get_server,
    _resolve_session,
    _serialize_session,
    _serialize_window,
    handle_tool_errors,
)
from libtmux.mcp.models import SessionInfo, WindowInfo

if t.TYPE_CHECKING:
    from fastmcp import FastMCP


@handle_tool_errors
def list_windows(
    session_name: str | None = None,
    session_id: str | None = None,
    socket_name: str | None = None,
    filters: dict[str, str] | str | None = None,
) -> list[WindowInfo]:
    """List windows in a tmux session, or all windows across sessions.

    Only searches window metadata (name, index, layout). To search
    the actual text visible in terminal panes, use search_panes instead.

    Parameters
    ----------
    session_name : str, optional
        Session name to look up. If omitted along with session_id,
        returns windows from all sessions.
    session_id : str, optional
        Session ID (e.g. '$1') to look up.
    socket_name : str, optional
        tmux socket name. Defaults to LIBTMUX_SOCKET env var.
    filters : dict or str, optional
        Django-style filters as a dict (e.g. ``{"window_name__contains": "dev"}``)
        or as a JSON string. Some MCP clients require the string form.

    Returns
    -------
    list[WindowInfo]
        List of serialized window objects.
    """
    server = _get_server(socket_name=socket_name)
    if session_name is not None or session_id is not None:
        session = _resolve_session(
            server, session_name=session_name, session_id=session_id
        )
        windows = session.windows
    else:
        windows = server.windows
    return _apply_filters(windows, filters, _serialize_window)


@handle_tool_errors
def create_window(
    session_name: str | None = None,
    session_id: str | None = None,
    window_name: str | None = None,
    start_directory: str | None = None,
    attach: bool = False,
    direction: t.Literal["before", "after"] | None = None,
    socket_name: str | None = None,
) -> WindowInfo:
    """Create a new window in a tmux session.

    Parameters
    ----------
    session_name : str, optional
        Session name to look up.
    session_id : str, optional
        Session ID (e.g. '$1') to look up.
    window_name : str, optional
        Name for the new window.
    start_directory : str, optional
        Working directory for the new window.
    attach : bool, optional
        Whether to make the new window active.
    direction : str, optional
        Window placement direction.
    socket_name : str, optional
        tmux socket name. Defaults to LIBTMUX_SOCKET env var.

    Returns
    -------
    WindowInfo
        Serialized window object.
    """
    server = _get_server(socket_name=socket_name)
    session = _resolve_session(server, session_name=session_name, session_id=session_id)
    kwargs: dict[str, t.Any] = {}
    if window_name is not None:
        kwargs["window_name"] = window_name
    if start_directory is not None:
        kwargs["start_directory"] = start_directory
    kwargs["attach"] = attach
    if direction is not None:
        direction_map: dict[str, WindowDirection] = {
            "before": WindowDirection.Before,
            "after": WindowDirection.After,
        }
        resolved = direction_map.get(direction)
        if resolved is None:
            from fastmcp.exceptions import ToolError

            valid = ", ".join(sorted(direction_map))
            msg = f"Invalid direction: {direction!r}. Valid: {valid}"
            raise ToolError(msg)
        kwargs["direction"] = resolved
    window = session.new_window(**kwargs)
    return _serialize_window(window)


@handle_tool_errors
def rename_session(
    new_name: str,
    session_name: str | None = None,
    session_id: str | None = None,
    socket_name: str | None = None,
) -> SessionInfo:
    """Rename a tmux session.

    Parameters
    ----------
    new_name : str
        New name for the session.
    session_name : str, optional
        Current session name to look up.
    session_id : str, optional
        Session ID (e.g. '$1') to look up.
    socket_name : str, optional
        tmux socket name. Defaults to LIBTMUX_SOCKET env var.

    Returns
    -------
    SessionInfo
        Serialized session object.
    """
    server = _get_server(socket_name=socket_name)
    session = _resolve_session(server, session_name=session_name, session_id=session_id)
    session = session.rename_session(new_name)
    return _serialize_session(session)


@handle_tool_errors
def kill_session(
    session_name: str | None = None,
    session_id: str | None = None,
    socket_name: str | None = None,
) -> str:
    """Kill a tmux session.

    Parameters
    ----------
    session_name : str, optional
        Session name to look up.
    session_id : str, optional
        Session ID (e.g. '$1') to look up.
    socket_name : str, optional
        tmux socket name. Defaults to LIBTMUX_SOCKET env var.

    Returns
    -------
    str
        Confirmation message.
    """
    server = _get_server(socket_name=socket_name)
    session = _resolve_session(server, session_name=session_name, session_id=session_id)
    name = session.session_name or session.session_id
    session.kill()
    return f"Session killed: {name}"


def register(mcp: FastMCP) -> None:
    """Register session-level tools with the MCP instance."""
    _RO = {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    _IDEM = {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    mcp.tool(title="List Windows", annotations=_RO)(list_windows)
    mcp.tool(
        title="Create Window",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )(create_window)
    mcp.tool(title="Rename Session", annotations=_IDEM)(rename_session)
    mcp.tool(
        title="Kill Session",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )(kill_session)
