"""MCP tools for tmux window operations."""

from __future__ import annotations

import json
import typing as t

from libtmux.constants import PaneDirection
from libtmux.mcp._utils import (
    _get_server,
    _resolve_pane,
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
) -> str:
    """List all panes in a tmux window.

    Parameters
    ----------
    session_name : str, optional
        Session name to resolve the window from.
    session_id : str, optional
        Session ID to resolve the window from.
    window_id : str, optional
        Window ID (e.g. '@1').
    window_index : str, optional
        Window index within the session.
    socket_name : str, optional
        tmux socket name.

    Returns
    -------
    str
        JSON array of serialized pane objects.
    """
    server = _get_server(socket_name=socket_name)
    window = _resolve_window(
        server,
        window_id=window_id,
        window_index=window_index,
        session_name=session_name,
        session_id=session_id,
    )
    return json.dumps([_serialize_pane(p) for p in window.panes])


@handle_tool_errors
def split_window(
    pane_id: str | None = None,
    session_name: str | None = None,
    window_id: str | None = None,
    window_index: str | None = None,
    direction: str | None = None,
    size: str | int | None = None,
    start_directory: str | None = None,
    shell: str | None = None,
    socket_name: str | None = None,
) -> str:
    """Split a tmux window to create a new pane.

    Parameters
    ----------
    pane_id : str, optional
        Pane ID to split from. If given, the pane's window is used.
    session_name : str, optional
        Session name.
    window_id : str, optional
        Window ID (e.g. '@1').
    window_index : str, optional
        Window index within the session.
    direction : str, optional
        Split direction: 'above', 'below', 'left', or 'right'.
    size : str or int, optional
        Size of the new pane (percentage or line count).
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

    if pane_id is not None:
        pane = _resolve_pane(server, pane_id=pane_id)
        window = pane.window
    else:
        window = _resolve_window(
            server,
            window_id=window_id,
            window_index=window_index,
            session_name=session_name,
        )

    pane_dir: PaneDirection | None = None
    if direction is not None:
        pane_dir = _DIRECTION_MAP.get(direction.lower())

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
        Layout name (e.g. 'even-horizontal', 'tiled') or custom layout string.
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
    cmd_args: list[str] = []
    if width is not None:
        cmd_args.extend(["-x", str(width)])
    if height is not None:
        cmd_args.extend(["-y", str(height)])
    if cmd_args:
        window.cmd("resize-window", *cmd_args)
    return json.dumps(_serialize_window(window))


def register(mcp: FastMCP) -> None:
    """Register window-level tools with the MCP instance."""
    mcp.tool(annotations={"readOnlyHint": True})(list_panes)
    mcp.tool(annotations={"destructiveHint": False})(split_window)
    mcp.tool(annotations={"destructiveHint": False})(rename_window)
    mcp.tool(annotations={"destructiveHint": True})(kill_window)
    mcp.tool(annotations={"destructiveHint": False})(select_layout)
    mcp.tool(annotations={"destructiveHint": False})(resize_window)
