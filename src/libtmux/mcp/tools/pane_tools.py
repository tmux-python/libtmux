"""MCP tools for tmux pane operations."""

from __future__ import annotations

import re
import typing as t

from libtmux.mcp._utils import (
    _get_caller_pane_id,
    _get_server,
    _resolve_pane,
    _resolve_session,
    _serialize_pane,
    handle_tool_errors,
)
from libtmux.mcp.models import PaneContentMatch, PaneInfo

if t.TYPE_CHECKING:
    from fastmcp import FastMCP


@handle_tool_errors
def send_keys(
    keys: str,
    pane_id: str | None = None,
    session_name: str | None = None,
    session_id: str | None = None,
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
        Pane ID (e.g. '%1').
    session_name : str, optional
        Session name for pane resolution.
    session_id : str, optional
        Session ID (e.g. '$1') for pane resolution.
    window_id : str, optional
        Window ID for pane resolution.
    enter : bool
        Whether to press Enter after sending keys. Default True.
    literal : bool
        Whether to send keys literally (no tmux interpretation). Default False.
    suppress_history : bool
        Whether to suppress shell history by prepending a space.
        Only works in shells that support HISTCONTROL. Default False.
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
        session_id=session_id,
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
    session_id: str | None = None,
    window_id: str | None = None,
    start: int | None = None,
    end: int | None = None,
    socket_name: str | None = None,
) -> str:
    """Capture the visible contents of a tmux pane.

    This is the tool for reading what is displayed in a terminal. Use
    search_panes to search for text across multiple panes at once.

    Parameters
    ----------
    pane_id : str, optional
        Pane ID (e.g. '%1').
    session_name : str, optional
        Session name for pane resolution.
    session_id : str, optional
        Session ID (e.g. '$1') for pane resolution.
    window_id : str, optional
        Window ID for pane resolution.
    start : int, optional
        Start line number. 0 is the first visible line. Negative values
        reach into scrollback history (e.g. -100 for last 100 lines).
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
        session_id=session_id,
        window_id=window_id,
    )
    lines = pane.capture_pane(start=start, end=end)
    return "\n".join(lines)


@handle_tool_errors
def resize_pane(
    pane_id: str | None = None,
    session_name: str | None = None,
    session_id: str | None = None,
    window_id: str | None = None,
    height: int | None = None,
    width: int | None = None,
    zoom: bool | None = None,
    socket_name: str | None = None,
) -> PaneInfo:
    """Resize a tmux pane.

    Parameters
    ----------
    pane_id : str, optional
        Pane ID (e.g. '%1').
    session_name : str, optional
        Session name for pane resolution.
    session_id : str, optional
        Session ID (e.g. '$1') for pane resolution.
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
    PaneInfo
        Serialized pane object.
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
        session_id=session_id,
        window_id=window_id,
    )
    if zoom is not None:
        window = pane.window
        result = window.cmd("display-message", "-p", "#{window_zoomed_flag}")
        is_zoomed = bool(result.stdout) and result.stdout[0] == "1"
        if zoom and not is_zoomed:
            pane.resize(zoom=True)
        elif not zoom and is_zoomed:
            pane.resize(zoom=True)  # toggle off
    else:
        pane.resize(height=height, width=width)
    return _serialize_pane(pane)


@handle_tool_errors
def kill_pane(
    pane_id: str | None = None,
    session_name: str | None = None,
    session_id: str | None = None,
    window_id: str | None = None,
    socket_name: str | None = None,
) -> str:
    """Kill (close) a tmux pane.

    Parameters
    ----------
    pane_id : str, optional
        Pane ID (e.g. '%1').
    session_name : str, optional
        Session name for pane resolution.
    session_id : str, optional
        Session ID (e.g. '$1') for pane resolution.
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
        session_id=session_id,
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
    session_id: str | None = None,
    window_id: str | None = None,
    socket_name: str | None = None,
) -> PaneInfo:
    """Set the title of a tmux pane.

    Parameters
    ----------
    title : str
        The new pane title.
    pane_id : str, optional
        Pane ID (e.g. '%1').
    session_name : str, optional
        Session name for pane resolution.
    session_id : str, optional
        Session ID (e.g. '$1') for pane resolution.
    window_id : str, optional
        Window ID for pane resolution.
    socket_name : str, optional
        tmux socket name.

    Returns
    -------
    PaneInfo
        Serialized pane object.
    """
    server = _get_server(socket_name=socket_name)
    pane = _resolve_pane(
        server,
        pane_id=pane_id,
        session_name=session_name,
        session_id=session_id,
        window_id=window_id,
    )
    pane.set_title(title)
    return _serialize_pane(pane)


@handle_tool_errors
def get_pane_info(
    pane_id: str | None = None,
    session_name: str | None = None,
    session_id: str | None = None,
    window_id: str | None = None,
    socket_name: str | None = None,
) -> PaneInfo:
    """Get detailed information about a tmux pane.

    Parameters
    ----------
    pane_id : str, optional
        Pane ID (e.g. '%1').
    session_name : str, optional
        Session name for pane resolution.
    session_id : str, optional
        Session ID (e.g. '$1') for pane resolution.
    window_id : str, optional
        Window ID for pane resolution.
    socket_name : str, optional
        tmux socket name.

    Returns
    -------
    PaneInfo
        Serialized pane details.
    """
    server = _get_server(socket_name=socket_name)
    pane = _resolve_pane(
        server,
        pane_id=pane_id,
        session_name=session_name,
        session_id=session_id,
        window_id=window_id,
    )
    return _serialize_pane(pane)


@handle_tool_errors
def clear_pane(
    pane_id: str | None = None,
    session_name: str | None = None,
    session_id: str | None = None,
    window_id: str | None = None,
    socket_name: str | None = None,
) -> str:
    """Clear the contents of a tmux pane.

    Parameters
    ----------
    pane_id : str, optional
        Pane ID (e.g. '%1').
    session_name : str, optional
        Session name for pane resolution.
    session_id : str, optional
        Session ID (e.g. '$1') for pane resolution.
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
        session_id=session_id,
        window_id=window_id,
    )
    pane.reset()
    return f"Pane cleared: {pane.pane_id}"


@handle_tool_errors
def search_panes(
    pattern: str,
    session_name: str | None = None,
    session_id: str | None = None,
    match_case: bool = False,
    content_start: int | None = None,
    content_end: int | None = None,
    socket_name: str | None = None,
) -> list[PaneContentMatch]:
    """Search for text across all pane contents.

    Use this when users ask what panes 'contain', 'mention', or 'show'.
    Searches each pane's visible content and returns panes where the
    pattern is found, with matching lines.

    Parameters
    ----------
    pattern : str
        Text or regex pattern to search for in pane contents.
    session_name : str, optional
        Limit search to panes in this session.
    session_id : str, optional
        Limit search to panes in this session (by ID).
    match_case : bool
        Whether to match case. Default False (case-insensitive).
    content_start : int, optional
        Start line for capture. Negative values reach into scrollback.
    content_end : int, optional
        End line for capture.
    socket_name : str, optional
        tmux socket name.

    Returns
    -------
    list[PaneContentMatch]
        Panes with matching content, including matched lines.
    """
    from fastmcp.exceptions import ToolError

    flags = 0 if match_case else re.IGNORECASE
    try:
        compiled = re.compile(pattern, flags)
    except re.error as e:
        msg = f"Invalid regex pattern: {e}"
        raise ToolError(msg) from e

    server = _get_server(socket_name=socket_name)

    uses_scrollback = content_start is not None or content_end is not None

    # Detect if pattern contains regex metacharacters that would break
    # tmux's glob-based #{C:} filter. When regex is needed, skip the tmux
    # fast path and capture all panes for Python-side matching.
    _REGEX_META = re.compile(r"[\\.*+?{}()\[\]|^$]")
    is_plain_text = not _REGEX_META.search(pattern)

    if not uses_scrollback and is_plain_text:
        # Phase 1: Fast filter via tmux's C-level window_pane_search().
        # #{C/i:pattern} searches visible pane content in C, returning only
        # matching pane IDs without capturing full content.
        case_flag = "" if match_case else "i"
        tmux_filter = (
            f"#{{C/{case_flag}:{pattern}}}" if case_flag else f"#{{C:{pattern}}}"
        )

        cmd_args: list[str] = ["list-panes"]
        if session_name is not None or session_id is not None:
            session = _resolve_session(
                server, session_name=session_name, session_id=session_id
            )
            cmd_args.extend(["-t", session.session_id or ""])
            cmd_args.append("-s")
        else:
            cmd_args.append("-a")
        cmd_args.extend(["-f", tmux_filter, "-F", "#{pane_id}"])

        result = server.cmd(*cmd_args)
        matching_pane_ids = set(result.stdout) if result.stdout else set()
    else:
        # Regex pattern or scrollback requested — fall back to capturing
        # all panes and matching in Python.
        if session_name is not None or session_id is not None:
            session = _resolve_session(
                server, session_name=session_name, session_id=session_id
            )
            all_panes = session.panes
        else:
            all_panes = server.panes
        matching_pane_ids = {p.pane_id for p in all_panes if p.pane_id is not None}

    # Phase 2: Capture matching panes and extract matched lines.
    caller_pane_id = _get_caller_pane_id()
    matches: list[PaneContentMatch] = []
    for pane_id_str in matching_pane_ids:
        pane = server.panes.get(pane_id=pane_id_str, default=None)
        if pane is None:
            continue

        lines = pane.capture_pane(start=content_start, end=content_end)
        matched_lines = [line for line in lines if compiled.search(line)]

        if not matched_lines:
            continue

        window = pane.window
        session_obj = pane.session
        matches.append(
            PaneContentMatch(
                pane_id=pane_id_str,
                pane_current_command=getattr(pane, "pane_current_command", None),
                pane_current_path=getattr(pane, "pane_current_path", None),
                window_id=pane.window_id,
                window_name=getattr(window, "window_name", None),
                session_id=pane.session_id,
                session_name=getattr(session_obj, "session_name", None),
                matched_lines=matched_lines,
                is_caller=(pane_id_str == caller_pane_id if caller_pane_id else None),
            )
        )

    return matches


def register(mcp: FastMCP) -> None:
    """Register pane-level tools with the MCP instance."""
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
    mcp.tool(
        title="Send Keys",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )(send_keys)
    mcp.tool(title="Capture Pane", annotations=_RO)(capture_pane)
    mcp.tool(title="Resize Pane", annotations=_IDEM)(resize_pane)
    mcp.tool(
        title="Kill Pane",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )(kill_pane)
    mcp.tool(title="Set Pane Title", annotations=_IDEM)(set_pane_title)
    mcp.tool(title="Get Pane Info", annotations=_RO)(get_pane_info)
    mcp.tool(title="Clear Pane", annotations=_IDEM)(clear_pane)
    mcp.tool(title="Search Panes", annotations=_RO)(search_panes)
