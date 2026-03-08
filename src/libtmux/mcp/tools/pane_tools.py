"""MCP tools for tmux pane operations."""

from __future__ import annotations

import json
import typing as t

from libtmux.mcp._utils import (
    _get_server,
    _resolve_pane,
    _serialize_pane,
    handle_tool_errors,
)

if t.TYPE_CHECKING:
    from fastmcp import FastMCP


@handle_tool_errors
def send_keys(
    keys: str,
    pane_id: str | None = None,
    session_name: str | None = None,
    window_id: str | None = None,
    enter: bool = True,
    literal: bool = False,
    suppress_history: bool = False,
    socket_name: str | None = None,
) -> str:
    """Send keys (commands or text) to a tmux pane.

    Parameters
    ----------
    keys : str
        The keys or text to send.
    pane_id : str, optional
        Pane ID (e.g. '%%1').
    session_name : str, optional
        Session name for pane resolution.
    window_id : str, optional
        Window ID for pane resolution.
    enter : bool
        Whether to press Enter after sending keys. Default True.
    literal : bool
        Whether to send keys literally (no tmux interpretation). Default False.
    suppress_history : bool
        Whether to suppress shell history. Default False.
    socket_name : str, optional
        tmux socket name.

    Returns
    -------
    str
        Confirmation message.
    """
    server = _get_server(socket_name=socket_name)
    pane = _resolve_pane(
        server,
        pane_id=pane_id,
        session_name=session_name,
        window_id=window_id,
    )
    pane.send_keys(
        keys,
        enter=enter,
        suppress_history=suppress_history,
        literal=literal,
    )
    return f"Keys sent to pane {pane.pane_id}"


@handle_tool_errors
def capture_pane(
    pane_id: str | None = None,
    session_name: str | None = None,
    window_id: str | None = None,
    start: int | None = None,
    end: int | None = None,
    socket_name: str | None = None,
) -> str:
    """Capture the visible contents of a tmux pane.

    Parameters
    ----------
    pane_id : str, optional
        Pane ID (e.g. '%%1').
    session_name : str, optional
        Session name for pane resolution.
    window_id : str, optional
        Window ID for pane resolution.
    start : int, optional
        Start line number (negative for scrollback history).
    end : int, optional
        End line number.
    socket_name : str, optional
        tmux socket name.

    Returns
    -------
    str
        Captured pane content as text.
    """
    server = _get_server(socket_name=socket_name)
    pane = _resolve_pane(
        server,
        pane_id=pane_id,
        session_name=session_name,
        window_id=window_id,
    )
    lines = pane.capture_pane(start=start, end=end)
    return "\n".join(lines)


@handle_tool_errors
def resize_pane(
    pane_id: str | None = None,
    session_name: str | None = None,
    window_id: str | None = None,
    height: int | None = None,
    width: int | None = None,
    zoom: bool | None = None,
    socket_name: str | None = None,
) -> str:
    """Resize a tmux pane.

    Parameters
    ----------
    pane_id : str, optional
        Pane ID (e.g. '%%1').
    session_name : str, optional
        Session name for pane resolution.
    window_id : str, optional
        Window ID for pane resolution.
    height : int, optional
        New height in lines.
    width : int, optional
        New width in columns.
    zoom : bool, optional
        Toggle pane zoom. If True, zoom the pane. If False, unzoom.
    socket_name : str, optional
        tmux socket name.

    Returns
    -------
    str
        JSON of the updated pane.
    """
    from fastmcp.exceptions import ToolError

    if zoom is not None and (height is not None or width is not None):
        msg = "Cannot combine zoom with height/width"
        raise ToolError(msg)

    server = _get_server(socket_name=socket_name)
    pane = _resolve_pane(
        server,
        pane_id=pane_id,
        session_name=session_name,
        window_id=window_id,
    )
    if zoom is not None:
        window = pane.window
        is_zoomed = getattr(window, "window_zoomed_flag", "0") == "1"
        if zoom and not is_zoomed:
            pane.resize(zoom=True)
        elif not zoom and is_zoomed:
            pane.resize(zoom=True)  # toggle off
    else:
        pane.resize(height=height, width=width)
    return json.dumps(_serialize_pane(pane))


@handle_tool_errors
def kill_pane(
    pane_id: str | None = None,
    session_name: str | None = None,
    window_id: str | None = None,
    socket_name: str | None = None,
) -> str:
    """Kill (close) a tmux pane.

    Parameters
    ----------
    pane_id : str, optional
        Pane ID (e.g. '%%1').
    session_name : str, optional
        Session name for pane resolution.
    window_id : str, optional
        Window ID for pane resolution.
    socket_name : str, optional
        tmux socket name.

    Returns
    -------
    str
        Confirmation message.
    """
    server = _get_server(socket_name=socket_name)
    pane = _resolve_pane(
        server,
        pane_id=pane_id,
        session_name=session_name,
        window_id=window_id,
    )
    pid = pane.pane_id
    pane.kill()
    return f"Pane killed: {pid}"


@handle_tool_errors
def set_pane_title(
    title: str,
    pane_id: str | None = None,
    session_name: str | None = None,
    window_id: str | None = None,
    socket_name: str | None = None,
) -> str:
    """Set the title of a tmux pane.

    Parameters
    ----------
    title : str
        The new pane title.
    pane_id : str, optional
        Pane ID (e.g. '%%1').
    session_name : str, optional
        Session name for pane resolution.
    window_id : str, optional
        Window ID for pane resolution.
    socket_name : str, optional
        tmux socket name.

    Returns
    -------
    str
        JSON of the updated pane.
    """
    server = _get_server(socket_name=socket_name)
    pane = _resolve_pane(
        server,
        pane_id=pane_id,
        session_name=session_name,
        window_id=window_id,
    )
    pane.set_title(title)
    return json.dumps(_serialize_pane(pane))


@handle_tool_errors
def get_pane_info(
    pane_id: str | None = None,
    session_name: str | None = None,
    window_id: str | None = None,
    socket_name: str | None = None,
) -> str:
    """Get detailed information about a tmux pane.

    Parameters
    ----------
    pane_id : str, optional
        Pane ID (e.g. '%%1').
    session_name : str, optional
        Session name for pane resolution.
    window_id : str, optional
        Window ID for pane resolution.
    socket_name : str, optional
        tmux socket name.

    Returns
    -------
    str
        JSON of pane details.
    """
    server = _get_server(socket_name=socket_name)
    pane = _resolve_pane(
        server,
        pane_id=pane_id,
        session_name=session_name,
        window_id=window_id,
    )
    return json.dumps(_serialize_pane(pane))


@handle_tool_errors
def clear_pane(
    pane_id: str | None = None,
    session_name: str | None = None,
    window_id: str | None = None,
    socket_name: str | None = None,
) -> str:
    """Clear the contents of a tmux pane.

    Parameters
    ----------
    pane_id : str, optional
        Pane ID (e.g. '%%1').
    session_name : str, optional
        Session name for pane resolution.
    window_id : str, optional
        Window ID for pane resolution.
    socket_name : str, optional
        tmux socket name.

    Returns
    -------
    str
        Confirmation message.
    """
    server = _get_server(socket_name=socket_name)
    pane = _resolve_pane(
        server,
        pane_id=pane_id,
        session_name=session_name,
        window_id=window_id,
    )
    pane.clear()
    return f"Pane cleared: {pane.pane_id}"


def register(mcp: FastMCP) -> None:
    """Register pane-level tools with the MCP instance."""
    mcp.tool(annotations={"destructiveHint": True, "idempotentHint": False})(send_keys)
    mcp.tool(annotations={"readOnlyHint": True})(capture_pane)
    mcp.tool(annotations={"destructiveHint": False})(resize_pane)
    mcp.tool(annotations={"destructiveHint": True})(kill_pane)
    mcp.tool(annotations={"destructiveHint": False})(set_pane_title)
    mcp.tool(annotations={"readOnlyHint": True})(get_pane_info)
    mcp.tool(annotations={"destructiveHint": False})(clear_pane)
