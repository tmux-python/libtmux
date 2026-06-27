"""tmux:// hierarchy resources over the engine.

Re-expose the server -> session -> window -> pane tree as MCP resources, built on
the curated vocabulary list/capture verbs. The engine binds one socket, so
libtmux-mcp's ``{?socket_name}`` query var is dropped. Every body is ``async``
and runs over the async vocabulary -- a sync server's engine is wrapped once
(:class:`~.vocabulary._bridge.SyncToAsyncEngine`), so there is no sync/async
duplication.
"""

from __future__ import annotations

import json
import typing as t

from fastmcp.exceptions import ResourceError

from libtmux.experimental.mcp import vocabulary

if t.TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from fastmcp import FastMCP

    from libtmux.experimental.engines.base import AsyncTmuxEngine, TmuxEngine

_JSON_MIME = "application/json"
_TEXT_MIME = "text/plain"


def _json(rows: Iterable[Mapping[str, str]]) -> str:
    """Serialize tmux format rows to a pretty JSON array."""
    return json.dumps([dict(row) for row in rows], indent=2)


def register_resources(
    mcp: FastMCP,
    engine: TmuxEngine | AsyncTmuxEngine,
    *,
    is_async: bool,
) -> None:
    """Register the ``tmux://`` hierarchy resources, bound to *engine*."""
    from libtmux.experimental.mcp.vocabulary._bridge import SyncToAsyncEngine

    if is_async:
        aengine = t.cast("AsyncTmuxEngine", engine)
    else:
        aengine = t.cast(
            "AsyncTmuxEngine",
            SyncToAsyncEngine(t.cast("TmuxEngine", engine)),
        )

    @mcp.resource("tmux://sessions", title="All sessions", mime_type=_JSON_MIME)
    async def get_sessions() -> str:
        """All tmux sessions as a JSON array."""
        return _json((await vocabulary.alist_sessions(aengine)).rows)

    @mcp.resource(
        "tmux://sessions/{session_name}",
        title="Session detail",
        mime_type=_JSON_MIME,
    )
    async def get_session(session_name: str) -> str:
        """One session plus its windows."""
        sessions = [
            row
            for row in (await vocabulary.alist_sessions(aengine)).rows
            if row.get("session_name") == session_name
        ]
        if not sessions:
            msg = f"session not found: {session_name}"
            raise ResourceError(msg)
        windows = [
            row
            for row in (await vocabulary.alist_windows(aengine, all_windows=True)).rows
            if row.get("session_name") == session_name
        ]
        result: dict[str, t.Any] = dict(sessions[0])
        result["windows"] = [dict(window) for window in windows]
        return json.dumps(result, indent=2)

    @mcp.resource(
        "tmux://sessions/{session_name}/windows",
        title="Session windows",
        mime_type=_JSON_MIME,
    )
    async def get_session_windows(session_name: str) -> str:
        """Return the windows of a session as a JSON array."""
        windows = [
            row
            for row in (await vocabulary.alist_windows(aengine, all_windows=True)).rows
            if row.get("session_name") == session_name
        ]
        return _json(windows)

    @mcp.resource(
        "tmux://sessions/{session_name}/windows/{window_index}",
        title="Window detail",
        mime_type=_JSON_MIME,
    )
    async def get_window(session_name: str, window_index: str) -> str:
        """One window plus its panes."""
        windows = [
            row
            for row in (await vocabulary.alist_windows(aengine, all_windows=True)).rows
            if row.get("session_name") == session_name
            and row.get("window_index") == window_index
        ]
        if not windows:
            msg = f"window not found: {session_name}:{window_index}"
            raise ResourceError(msg)
        panes = [
            row
            for row in (await vocabulary.alist_panes(aengine, all_panes=True)).rows
            if row.get("session_name") == session_name
            and row.get("window_index") == window_index
        ]
        result: dict[str, t.Any] = dict(windows[0])
        result["panes"] = [dict(pane) for pane in panes]
        return json.dumps(result, indent=2)

    @mcp.resource("tmux://panes/{pane_id}", title="Pane detail", mime_type=_JSON_MIME)
    async def get_pane(pane_id: str) -> str:
        """One pane's metadata."""
        panes = [
            row
            for row in (await vocabulary.alist_panes(aengine, all_panes=True)).rows
            if row.get("pane_id") == pane_id
        ]
        if not panes:
            msg = f"pane not found: {pane_id}"
            raise ResourceError(msg)
        return json.dumps(dict(panes[0]), indent=2)

    @mcp.resource(
        "tmux://panes/{pane_id}/content",
        title="Pane content",
        mime_type=_TEXT_MIME,
    )
    async def get_pane_content(pane_id: str) -> str:
        """Return a pane's captured terminal text."""
        capture = await vocabulary.acapture_pane(aengine, pane_id)
        return "\n".join(capture.lines)

    # The decorator registers each resource; bind the names so linters do not
    # read them as dead code.
    _ = (
        get_sessions,
        get_session,
        get_session_windows,
        get_window,
        get_pane,
        get_pane_content,
    )
