"""MCP tools for tmux session operations."""

from __future__ import annotations

import json
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

if t.TYPE_CHECKING:
    from fastmcp import FastMCP


@handle_tool_errors
def list_windows(
    session_name: str | None = None,
    session_id: str | None = None,
    socket_name: str | None = None,
    filters: dict[str, str] | None = None,
) -> str:
    """List windows in a tmux session, or all windows across sessions.

    Parameters
    ----------
    session_name : str, optional
        Session name to look up. If omitted along with session_id,
        returns windows from all sessions.
    session_id : str, optional
        Session ID (e.g. '$1') to look up.
    socket_name : str, optional
        tmux socket name. Defaults to LIBTMUX_SOCKET env var.
    filters : dict, optional
        Django-style filters (e.g. ``{"window_name__contains": "dev"}``).

    Returns
    -------
    str
        JSON array of window objects.
    """
    server = _get_server(socket_name=socket_name)
    if session_name is not None or session_id is not None:
        session = _resolve_session(
            server, session_name=session_name, session_id=session_id
        )
        windows = session.windows
    else:
        windows = server.windows
    return json.dumps(_apply_filters(windows, filters, _serialize_window))


@handle_tool_errors
def create_window(
    session_name: str | None = None,
    session_id: str | None = None,
    window_name: str | None = None,
    start_directory: str | None = None,
    attach: bool = False,
    direction: str | None = None,
    socket_name: str | None = None,
) -> str:
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
        Window placement direction: "before" or "after".
    socket_name : str, optional
        tmux socket name. Defaults to LIBTMUX_SOCKET env var.

    Returns
    -------
    str
        JSON object of the created window.
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
        resolved = direction_map.get(direction.lower())
        if resolved is None:
            from fastmcp.exceptions import ToolError

            valid = ", ".join(sorted(direction_map))
            msg = f"Invalid direction: {direction!r}. Valid: {valid}"
            raise ToolError(msg)
        kwargs["direction"] = resolved
    window = session.new_window(**kwargs)
    return json.dumps(_serialize_window(window))


@handle_tool_errors
def rename_session(
    new_name: str,
    session_name: str | None = None,
    session_id: str | None = None,
    socket_name: str | None = None,
) -> str:
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
    str
        JSON object of the renamed session.
    """
    server = _get_server(socket_name=socket_name)
    session = _resolve_session(server, session_name=session_name, session_id=session_id)
    session = session.rename_session(new_name)
    return json.dumps(_serialize_session(session))


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
    mcp.tool(annotations={"readOnlyHint": True})(list_windows)
    mcp.tool(annotations={"destructiveHint": False})(create_window)
    mcp.tool(annotations={"destructiveHint": False})(rename_session)
    mcp.tool(annotations={"destructiveHint": True})(kill_session)
