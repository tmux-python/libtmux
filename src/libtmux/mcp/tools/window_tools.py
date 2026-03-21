"""MCP tools for tmux window operations."""

from __future__ import annotations

import json
import typing as t

from libtmux.constants import PaneDirection
from libtmux.mcp._utils import (
    _apply_filters,
    _get_server,
    _resolve_pane,
    _resolve_session,
    _resolve_window,
    _serialize_pane,
    _serialize_window,
    handle_tool_errors,
)

if t.TYPE_CHECKING:
    from fastmcp import FastMCP

_DIRECTION_MAP: dict[str, PaneDirection] = {
    "above": PaneDirection.Above,
    "below": PaneDirection.Below,
    "right": PaneDirection.Right,
    "left": PaneDirection.Left,
}


@handle_tool_errors
def list_panes(
    session_name: str | None = None,
    session_id: str | None = None,
    window_id: str | None = None,
    window_index: str | None = None,
    socket_name: str | None = None,
    filters: dict[str, str] | str | None = None,
) -> str:
    """List panes in a tmux window, session, or across the entire server.

    Parameters
    ----------
    session_name : str, optional
        Session name. If given without window params, lists all panes
        in the session.
    session_id : str, optional
        Session ID. If given without window params, lists all panes
        in the session.
    window_id : str, optional
        Window ID (e.g. '@1'). Scopes to a single window.
    window_index : str, optional
        Window index within the session. Scopes to a single window.
    socket_name : str, optional
        tmux socket name.
    filters : dict or str, optional
        Django-style filters as a dict
        (e.g. ``{"pane_current_command__contains": "vim"}``)
        or as a JSON string. Some MCP clients require the string form.

    Returns
    -------
    str
        JSON array of serialized pane objects.
    """
    server = _get_server(socket_name=socket_name)
    if window_id is not None or window_index is not None:
        window = _resolve_window(
            server,
            window_id=window_id,
            window_index=window_index,
            session_name=session_name,
            session_id=session_id,
        )
        panes = window.panes
    elif session_name is not None or session_id is not None:
        session = _resolve_session(
            server, session_name=session_name, session_id=session_id
        )
        panes = session.panes
    else:
        panes = server.panes
    return json.dumps(_apply_filters(panes, filters, _serialize_pane))


@handle_tool_errors
def split_window(
    pane_id: str | None = None,
    session_name: str | None = None,
    session_id: str | None = None,
    window_id: str | None = None,
    window_index: str | None = None,
    direction: t.Literal["above", "below", "left", "right"] | None = None,
    size: str | int | None = None,
    start_directory: str | None = None,
    shell: str | None = None,
    socket_name: str | None = None,
) -> str:
    """Split a tmux window to create a new pane.

    Parameters
    ----------
    pane_id : str, optional
        Pane ID to split from. If given, splits adjacent to this pane.
    session_name : str, optional
        Session name.
    session_id : str, optional
        Session ID (e.g. '$1').
    window_id : str, optional
        Window ID (e.g. '@1').
    window_index : str, optional
        Window index within the session.
    direction : str, optional
        Split direction.
    size : str or int, optional
        Size of the new pane. Use a string with '%%' suffix for
        percentage (e.g. '50%%') or an integer for lines/columns.
    start_directory : str, optional
        Working directory for the new pane.
    shell : str, optional
        Shell command to run in the new pane.
    socket_name : str, optional
        tmux socket name.

    Returns
    -------
    str
        JSON of the newly created pane.
    """
    server = _get_server(socket_name=socket_name)

    pane_dir: PaneDirection | None = None
    if direction is not None:
        pane_dir = _DIRECTION_MAP.get(direction)
        if pane_dir is None:
            from fastmcp.exceptions import ToolError

            valid = ", ".join(sorted(_DIRECTION_MAP))
            msg = f"Invalid direction: {direction!r}. Valid: {valid}"
            raise ToolError(msg)

    if pane_id is not None:
        pane = _resolve_pane(server, pane_id=pane_id)
        new_pane = pane.split(
            direction=pane_dir,
            size=size,
            start_directory=start_directory,
            shell=shell,
        )
    else:
        window = _resolve_window(
            server,
            window_id=window_id,
            window_index=window_index,
            session_name=session_name,
            session_id=session_id,
        )
        new_pane = window.split(
            direction=pane_dir,
            size=size,
            start_directory=start_directory,
            shell=shell,
        )
    return json.dumps(_serialize_pane(new_pane))


@handle_tool_errors
def rename_window(
    new_name: str,
    window_id: str | None = None,
    window_index: str | None = None,
    session_name: str | None = None,
    session_id: str | None = None,
    socket_name: str | None = None,
) -> str:
    """Rename a tmux window.

    Parameters
    ----------
    new_name : str
        The new name for the window.
    window_id : str, optional
        Window ID (e.g. '@1').
    window_index : str, optional
        Window index within the session.
    session_name : str, optional
        Session name.
    session_id : str, optional
        Session ID.
    socket_name : str, optional
        tmux socket name.

    Returns
    -------
    str
        JSON of the updated window.
    """
    server = _get_server(socket_name=socket_name)
    window = _resolve_window(
        server,
        window_id=window_id,
        window_index=window_index,
        session_name=session_name,
        session_id=session_id,
    )
    window.rename_window(new_name)
    return json.dumps(_serialize_window(window))


@handle_tool_errors
def kill_window(
    window_id: str | None = None,
    window_index: str | None = None,
    session_name: str | None = None,
    session_id: str | None = None,
    socket_name: str | None = None,
) -> str:
    """Kill (close) a tmux window.

    Parameters
    ----------
    window_id : str, optional
        Window ID (e.g. '@1').
    window_index : str, optional
        Window index within the session.
    session_name : str, optional
        Session name.
    session_id : str, optional
        Session ID.
    socket_name : str, optional
        tmux socket name.

    Returns
    -------
    str
        Confirmation message.
    """
    server = _get_server(socket_name=socket_name)
    window = _resolve_window(
        server,
        window_id=window_id,
        window_index=window_index,
        session_name=session_name,
        session_id=session_id,
    )
    wid = window.window_id
    window.kill()
    return f"Window killed: {wid}"


@handle_tool_errors
def select_layout(
    layout: str,
    window_id: str | None = None,
    window_index: str | None = None,
    session_name: str | None = None,
    session_id: str | None = None,
    socket_name: str | None = None,
) -> str:
    """Set the layout of a tmux window.

    Parameters
    ----------
    layout : str
        Layout name or custom layout string. Built-in layouts:
        'even-horizontal', 'even-vertical', 'main-horizontal',
        'main-horizontal-mirrored', 'main-vertical',
        'main-vertical-mirrored', 'tiled'.
    window_id : str, optional
        Window ID (e.g. '@1').
    window_index : str, optional
        Window index within the session.
    session_name : str, optional
        Session name.
    session_id : str, optional
        Session ID.
    socket_name : str, optional
        tmux socket name.

    Returns
    -------
    str
        JSON of the updated window.
    """
    server = _get_server(socket_name=socket_name)
    window = _resolve_window(
        server,
        window_id=window_id,
        window_index=window_index,
        session_name=session_name,
        session_id=session_id,
    )
    window.select_layout(layout)
    return json.dumps(_serialize_window(window))


@handle_tool_errors
def resize_window(
    window_id: str | None = None,
    window_index: str | None = None,
    session_name: str | None = None,
    session_id: str | None = None,
    height: int | None = None,
    width: int | None = None,
    socket_name: str | None = None,
) -> str:
    """Resize a tmux window.

    Parameters
    ----------
    window_id : str, optional
        Window ID (e.g. '@1').
    window_index : str, optional
        Window index within the session.
    session_name : str, optional
        Session name.
    session_id : str, optional
        Session ID.
    height : int, optional
        New height in lines.
    width : int, optional
        New width in columns.
    socket_name : str, optional
        tmux socket name.

    Returns
    -------
    str
        JSON of the updated window.
    """
    server = _get_server(socket_name=socket_name)
    window = _resolve_window(
        server,
        window_id=window_id,
        window_index=window_index,
        session_name=session_name,
        session_id=session_id,
    )
    window.resize(height=height, width=width)
    return json.dumps(_serialize_window(window))


def register(mcp: FastMCP) -> None:
    """Register window-level tools with the MCP instance."""
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
    mcp.tool(title="List Panes", annotations=_RO)(list_panes)
    mcp.tool(
        title="Split Window",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )(split_window)
    mcp.tool(title="Rename Window", annotations=_IDEM)(rename_window)
    mcp.tool(
        title="Kill Window",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )(kill_window)
    mcp.tool(title="Select Layout", annotations=_IDEM)(select_layout)
    mcp.tool(title="Resize Window", annotations=_IDEM)(resize_window)
