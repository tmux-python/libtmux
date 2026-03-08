"""Shared utilities for libtmux MCP server.

Provides server caching, object resolution, serialization, and error handling
for all MCP tool functions.
"""

from __future__ import annotations

import functools
import logging
import os
import typing as t

from libtmux import exc
from libtmux._internal.query_list import LOOKUP_NAME_MAP
from libtmux.server import Server

if t.TYPE_CHECKING:
    from libtmux.pane import Pane
    from libtmux.session import Session
    from libtmux.window import Window

logger = logging.getLogger(__name__)

_server_cache: dict[tuple[str | None, str | None, str | None], Server] = {}


def _get_server(
    socket_name: str | None = None,
    socket_path: str | None = None,
) -> Server:
    """Get or create a cached Server instance.

    Parameters
    ----------
    socket_name : str, optional
        tmux socket name (-L). Falls back to LIBTMUX_SOCKET env var.
    socket_path : str, optional
        tmux socket path (-S). Falls back to LIBTMUX_SOCKET_PATH env var.

    Returns
    -------
    Server
        A cached libtmux Server instance.
    """
    if socket_name is None:
        socket_name = os.environ.get("LIBTMUX_SOCKET")
    if socket_path is None:
        socket_path = os.environ.get("LIBTMUX_SOCKET_PATH")

    tmux_bin = os.environ.get("LIBTMUX_TMUX_BIN")

    cache_key = (socket_name, socket_path, tmux_bin)
    if cache_key in _server_cache:
        cached = _server_cache[cache_key]
        if not cached.is_alive():
            del _server_cache[cache_key]

    if cache_key not in _server_cache:
        kwargs: dict[str, t.Any] = {}
        if socket_name is not None:
            kwargs["socket_name"] = socket_name
        if socket_path is not None:
            kwargs["socket_path"] = socket_path
        if tmux_bin is not None:
            kwargs["tmux_bin"] = tmux_bin
        _server_cache[cache_key] = Server(**kwargs)

    return _server_cache[cache_key]


def _invalidate_server(
    socket_name: str | None = None,
    socket_path: str | None = None,
) -> None:
    """Evict a server from the cache.

    Parameters
    ----------
    socket_name : str, optional
        tmux socket name used in the cache key.
    socket_path : str, optional
        tmux socket path used in the cache key.
    """
    keys_to_remove = [
        key for key in _server_cache if key[0] == socket_name and key[1] == socket_path
    ]
    for key in keys_to_remove:
        del _server_cache[key]


def _resolve_session(
    server: Server,
    session_name: str | None = None,
    session_id: str | None = None,
) -> Session:
    """Resolve a session by name or ID.

    Parameters
    ----------
    server : Server
        The tmux server.
    session_name : str, optional
        Session name to look up.
    session_id : str, optional
        Session ID (e.g. '$1') to look up.

    Returns
    -------
    Session

    Raises
    ------
    exc.TmuxObjectDoesNotExist
        If no matching session is found.
    """
    if session_id is not None:
        session = server.sessions.get(session_id=session_id, default=None)
        if session is None:
            raise exc.TmuxObjectDoesNotExist(
                obj_key="session_id",
                obj_id=session_id,
                list_cmd="list-sessions",
            )
        return session

    if session_name is not None:
        session = server.sessions.get(session_name=session_name, default=None)
        if session is None:
            raise exc.TmuxObjectDoesNotExist(
                obj_key="session_name",
                obj_id=session_name,
                list_cmd="list-sessions",
            )
        return session

    sessions = server.sessions
    if not sessions:
        raise exc.TmuxObjectDoesNotExist(
            obj_key="session",
            obj_id="(any)",
            list_cmd="list-sessions",
        )
    return sessions[0]


def _resolve_window(
    server: Server,
    session: Session | None = None,
    window_id: str | None = None,
    window_index: str | None = None,
    session_name: str | None = None,
    session_id: str | None = None,
) -> Window:
    """Resolve a window by ID, index, or default.

    Parameters
    ----------
    server : Server
        The tmux server.
    session : Session, optional
        Session to search within.
    window_id : str, optional
        Window ID (e.g. '@1').
    window_index : str, optional
        Window index within the session.
    session_name : str, optional
        Session name for resolution.
    session_id : str, optional
        Session ID for resolution.

    Returns
    -------
    Window

    Raises
    ------
    exc.TmuxObjectDoesNotExist
        If no matching window is found.
    """
    if window_id is not None:
        window = server.windows.get(window_id=window_id, default=None)
        if window is None:
            raise exc.TmuxObjectDoesNotExist(
                obj_key="window_id",
                obj_id=window_id,
                list_cmd="list-windows",
            )
        return window

    if session is None:
        session = _resolve_session(
            server,
            session_name=session_name,
            session_id=session_id,
        )

    if window_index is not None:
        window = session.windows.get(window_index=window_index, default=None)
        if window is None:
            raise exc.TmuxObjectDoesNotExist(
                obj_key="window_index",
                obj_id=window_index,
                list_cmd="list-windows",
            )
        return window

    windows = session.windows
    if not windows:
        raise exc.NoWindowsExist()
    return windows[0]


def _resolve_pane(
    server: Server,
    pane_id: str | None = None,
    session_name: str | None = None,
    session_id: str | None = None,
    window_id: str | None = None,
    window_index: str | None = None,
    pane_index: str | None = None,
) -> Pane:
    """Resolve a pane by ID or hierarchical targeting.

    Parameters
    ----------
    server : Server
        The tmux server.
    pane_id : str, optional
        Pane ID (e.g. '%%1'). Globally unique within a server.
    session_name : str, optional
        Session name for hierarchical resolution.
    session_id : str, optional
        Session ID for hierarchical resolution.
    window_id : str, optional
        Window ID for hierarchical resolution.
    window_index : str, optional
        Window index for hierarchical resolution.
    pane_index : str, optional
        Pane index within the window.

    Returns
    -------
    Pane

    Raises
    ------
    exc.TmuxObjectDoesNotExist
        If no matching pane is found.
    """
    if pane_id is not None:
        pane = server.panes.get(pane_id=pane_id, default=None)
        if pane is None:
            raise exc.PaneNotFound(pane_id=pane_id)
        return pane

    window = _resolve_window(
        server,
        window_id=window_id,
        window_index=window_index,
        session_name=session_name,
        session_id=session_id,
    )

    if pane_index is not None:
        pane = window.panes.get(pane_index=pane_index, default=None)
        if pane is None:
            raise exc.PaneNotFound(pane_id=f"index:{pane_index}")
        return pane

    panes = window.panes
    if not panes:
        raise exc.PaneNotFound()
    return panes[0]


def _apply_filters(
    items: t.Any,
    filters: dict[str, str] | None,
    serializer: t.Callable[..., dict[str, t.Any]],
) -> list[dict[str, t.Any]]:
    """Apply QueryList filters and serialize results.

    Parameters
    ----------
    items : QueryList
        The QueryList of tmux objects to filter.
    filters : dict or None
        Django-style filter kwargs (e.g. ``{"session_name__contains": "dev"}``).
        If None or empty, all items are returned.
    serializer : callable
        Serializer function to convert each item to a dict.

    Returns
    -------
    list[dict]
        Serialized list of matching items.

    Raises
    ------
    ToolError
        If a filter key uses an invalid lookup operator.
    """
    if not filters:
        return [serializer(item) for item in items]

    from fastmcp.exceptions import ToolError

    valid_ops = sorted(LOOKUP_NAME_MAP.keys())
    for key in filters:
        if "__" in key:
            _field, op = key.rsplit("__", 1)
            if op not in LOOKUP_NAME_MAP:
                msg = (
                    f"Invalid filter operator '{op}' in '{key}'. "
                    f"Valid operators: {', '.join(valid_ops)}"
                )
                raise ToolError(msg)

    filtered = items.filter(**filters)
    return [serializer(item) for item in filtered]


def _serialize_session(session: Session) -> dict[str, t.Any]:
    """Serialize a Session to a JSON-compatible dict.

    Parameters
    ----------
    session : Session
        The session to serialize.

    Returns
    -------
    dict
        Session data including id, name, window count, dimensions.
    """
    return {
        "session_id": session.session_id,
        "session_name": session.session_name,
        "window_count": len(session.windows),
        "session_attached": getattr(session, "session_attached", None),
        "session_created": getattr(session, "session_created", None),
    }


def _serialize_window(window: Window) -> dict[str, t.Any]:
    """Serialize a Window to a JSON-compatible dict.

    Parameters
    ----------
    window : Window
        The window to serialize.

    Returns
    -------
    dict
        Window data including id, name, index, pane count, layout.
    """
    return {
        "window_id": window.window_id,
        "window_name": window.window_name,
        "window_index": window.window_index,
        "session_id": window.session_id,
        "session_name": getattr(window, "session_name", None),
        "pane_count": len(window.panes),
        "window_layout": getattr(window, "window_layout", None),
        "window_active": getattr(window, "window_active", None),
        "window_width": getattr(window, "window_width", None),
        "window_height": getattr(window, "window_height", None),
    }


def _serialize_pane(pane: Pane) -> dict[str, t.Any]:
    """Serialize a Pane to a JSON-compatible dict.

    Parameters
    ----------
    pane : Pane
        The pane to serialize.

    Returns
    -------
    dict
        Pane data including id, dimensions, current command, title.
    """
    return {
        "pane_id": pane.pane_id,
        "pane_index": getattr(pane, "pane_index", None),
        "pane_width": getattr(pane, "pane_width", None),
        "pane_height": getattr(pane, "pane_height", None),
        "pane_current_command": getattr(pane, "pane_current_command", None),
        "pane_current_path": getattr(pane, "pane_current_path", None),
        "pane_pid": getattr(pane, "pane_pid", None),
        "pane_title": getattr(pane, "pane_title", None),
        "pane_active": getattr(pane, "pane_active", None),
        "window_id": pane.window_id,
        "session_id": pane.session_id,
    }


P = t.ParamSpec("P")
R = t.TypeVar("R")


def handle_tool_errors(
    fn: t.Callable[P, R],
) -> t.Callable[P, R]:
    """Decorate MCP tool functions with standardized error handling.

    Catches libtmux exceptions and re-raises as ``ToolError`` so that
    MCP responses have ``isError=True`` with a descriptive message.
    """
    from fastmcp.exceptions import ToolError

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except exc.TmuxCommandNotFound as e:
            msg = "tmux binary not found. Ensure tmux is installed and in PATH."
            raise ToolError(msg) from e
        except exc.TmuxSessionExists as e:
            raise ToolError(str(e)) from e
        except exc.BadSessionName as e:
            raise ToolError(str(e)) from e
        except exc.TmuxObjectDoesNotExist as e:
            msg = f"Object not found: {e}"
            raise ToolError(msg) from e
        except exc.PaneNotFound as e:
            msg = f"Pane not found: {e}"
            raise ToolError(msg) from e
        except exc.LibTmuxException as e:
            msg = f"tmux error: {e}"
            raise ToolError(msg) from e
        except Exception as e:
            logger.exception("unexpected error in MCP tool %s", fn.__name__)
            msg = f"Unexpected error: {type(e).__name__}: {e}"
            raise ToolError(msg) from e

    return wrapper
