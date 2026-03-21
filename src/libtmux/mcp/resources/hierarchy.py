"""MCP resources for tmux object hierarchy."""

from __future__ import annotations

import json
import typing as t

from fastmcp.exceptions import ResourceError

from libtmux.mcp._utils import (
    _get_server,
    _serialize_pane,
    _serialize_session,
    _serialize_window,
)

if t.TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register hierarchy resources with the FastMCP instance."""

    @mcp.resource("tmux://sessions")
    def get_sessions() -> str:
        """List all tmux sessions.

        Returns
        -------
        str
            JSON array of session objects.
        """
        server = _get_server()
        sessions = [_serialize_session(s) for s in server.sessions]
        return json.dumps(sessions, indent=2)

    @mcp.resource("tmux://sessions/{session_name}")
    def get_session(session_name: str) -> str:
        """Get details of a specific tmux session.

        Parameters
        ----------
        session_name : str
            The session name.

        Returns
        -------
        str
            JSON object with session info and its windows.
        """
        server = _get_server()
        session = server.sessions.get(session_name=session_name, default=None)
        if session is None:
            msg = f"Session not found: {session_name}"
            raise ResourceError(msg)

        result = _serialize_session(session)
        result["windows"] = [_serialize_window(w) for w in session.windows]
        return json.dumps(result, indent=2)

    @mcp.resource("tmux://sessions/{session_name}/windows")
    def get_session_windows(session_name: str) -> str:
        """List all windows in a tmux session.

        Parameters
        ----------
        session_name : str
            The session name.

        Returns
        -------
        str
            JSON array of window objects.
        """
        server = _get_server()
        session = server.sessions.get(session_name=session_name, default=None)
        if session is None:
            msg = f"Session not found: {session_name}"
            raise ResourceError(msg)

        windows = [_serialize_window(w) for w in session.windows]
        return json.dumps(windows, indent=2)

    @mcp.resource("tmux://sessions/{session_name}/windows/{window_index}")
    def get_window(session_name: str, window_index: str) -> str:
        """Get details of a specific window in a session.

        Parameters
        ----------
        session_name : str
            The session name.
        window_index : str
            The window index within the session.

        Returns
        -------
        str
            JSON object with window info and its panes.
        """
        server = _get_server()
        session = server.sessions.get(session_name=session_name, default=None)
        if session is None:
            msg = f"Session not found: {session_name}"
            raise ResourceError(msg)

        window = session.windows.get(window_index=window_index, default=None)
        if window is None:
            msg = f"Window not found: index {window_index}"
            raise ResourceError(msg)

        result = _serialize_window(window)
        result["panes"] = [_serialize_pane(p) for p in window.panes]
        return json.dumps(result, indent=2)

    @mcp.resource("tmux://panes/{pane_id}")
    def get_pane(pane_id: str) -> str:
        """Get details of a specific pane.

        Parameters
        ----------
        pane_id : str
            The pane ID (e.g. '%1').

        Returns
        -------
        str
            JSON object of pane details.
        """
        server = _get_server()
        pane = server.panes.get(pane_id=pane_id, default=None)
        if pane is None:
            msg = f"Pane not found: {pane_id}"
            raise ResourceError(msg)

        return json.dumps(_serialize_pane(pane), indent=2)

    @mcp.resource("tmux://panes/{pane_id}/content")
    def get_pane_content(pane_id: str) -> str:
        """Capture and return the content of a pane.

        Parameters
        ----------
        pane_id : str
            The pane ID (e.g. '%1').

        Returns
        -------
        str
            Plain text captured pane content.
        """
        server = _get_server()
        pane = server.panes.get(pane_id=pane_id, default=None)
        if pane is None:
            msg = f"Pane not found: {pane_id}"
            raise ResourceError(msg)

        lines = pane.capture_pane()
        return "\n".join(lines)
