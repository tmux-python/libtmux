"""Utility functions for working with snapshots.

This module provides utility functions for filtering and serializing snapshots.
"""

from __future__ import annotations

import copy
import datetime
import typing as t

from .models.pane import PaneSnapshot
from .models.server import ServerSnapshot
from .models.session import SessionSnapshot
from .models.window import WindowSnapshot
from .types import SnapshotType


def filter_snapshot(
    snapshot: SnapshotType,
    filter_func: t.Callable[[SnapshotType], bool],
) -> SnapshotType | None:
    """Filter a snapshot tree based on a filter function.

    This recursively filters the snapshot tree based on the filter function.
    Parent-child relationships are maintained in the filtered snapshot.

    Parameters
    ----------
    snapshot : SnapshotType
        The snapshot to filter
    filter_func : Callable
        A function that takes a snapshot object and returns True to keep it
        or False to filter it out

    Returns
    -------
    SnapshotType | None
        A new filtered snapshot, or None if everything was filtered out
    """
    if isinstance(snapshot, ServerSnapshot):
        filtered_sessions: list[SessionSnapshot] = []

        for sess in snapshot.sessions_snapshot:
            session_copy = filter_snapshot(sess, filter_func)
            if session_copy is not None and isinstance(session_copy, SessionSnapshot):
                filtered_sessions.append(session_copy)

        if not filter_func(snapshot) and not filtered_sessions:
            return None

        server_copy = copy.deepcopy(snapshot)
        object.__setattr__(server_copy, "sessions_snapshot", filtered_sessions)

        windows_snapshot = []
        panes_snapshot = []
        for session in filtered_sessions:
            windows_snapshot.extend(session.windows_snapshot)
            for window in session.windows_snapshot:
                panes_snapshot.extend(window.panes_snapshot)

        object.__setattr__(server_copy, "windows_snapshot", windows_snapshot)
        object.__setattr__(server_copy, "panes_snapshot", panes_snapshot)

        return server_copy

    if isinstance(snapshot, SessionSnapshot):
        filtered_windows: list[WindowSnapshot] = []

        for w in snapshot.windows_snapshot:
            window_copy = filter_snapshot(w, filter_func)
            if window_copy is not None and isinstance(window_copy, WindowSnapshot):
                filtered_windows.append(window_copy)

        if not filter_func(snapshot) and not filtered_windows:
            return None

        session_copy = copy.deepcopy(snapshot)
        object.__setattr__(session_copy, "windows_snapshot", filtered_windows)
        return session_copy

    if isinstance(snapshot, WindowSnapshot):
        filtered_panes = [p for p in snapshot.panes_snapshot if filter_func(p)]

        if not filter_func(snapshot) and not filtered_panes:
            return None

        window_copy = copy.deepcopy(snapshot)
        object.__setattr__(window_copy, "panes_snapshot", filtered_panes)
        return window_copy

    if isinstance(snapshot, PaneSnapshot):
        if filter_func(snapshot):
            return snapshot
        return None

    return snapshot


def snapshot_to_dict(
    snapshot: SnapshotType | t.Any,
) -> dict[str, t.Any]:
    """Convert a snapshot to a dictionary, avoiding circular references.

    This is useful for serializing snapshots to JSON or other formats.

    Parameters
    ----------
    snapshot : SnapshotType | Any
        The snapshot to convert to a dictionary

    Returns
    -------
    dict
        A dictionary representation of the snapshot
    """
    if not isinstance(
        snapshot,
        (ServerSnapshot, SessionSnapshot, WindowSnapshot, PaneSnapshot),
    ):
        return t.cast("dict[str, t.Any]", snapshot)

    result: dict[str, t.Any] = {}

    for name, value in vars(snapshot).items():
        if name.startswith("_") or name in {
            "server",
            "server_snapshot",
            "session_snapshot",
            "window_snapshot",
        }:
            continue

        if (
            isinstance(value, list)
            and value
            and isinstance(
                value[0],
                (ServerSnapshot, SessionSnapshot, WindowSnapshot, PaneSnapshot),
            )
        ):
            result[name] = [snapshot_to_dict(item) for item in value]
        elif isinstance(
            value,
            (ServerSnapshot, SessionSnapshot, WindowSnapshot, PaneSnapshot),
        ):
            result[name] = snapshot_to_dict(value)
        elif hasattr(value, "list") and callable(getattr(value, "list", None)):
            try:
                items = value.list()
                result[name] = []
                for item in items:
                    if isinstance(
                        item,
                        (ServerSnapshot, SessionSnapshot, WindowSnapshot, PaneSnapshot),
                    ):
                        result[name].append(snapshot_to_dict(item))
                    else:
                        result[name] = str(value)
            except Exception:
                result[name] = str(value)
        elif isinstance(value, datetime.datetime):
            result[name] = str(value)
        else:
            result[name] = value

    return result


def snapshot_active_only(
    full_snapshot: ServerSnapshot,
) -> ServerSnapshot:
    """Return a filtered snapshot containing only active sessions, windows, and panes.

    Parameters
    ----------
    full_snapshot : ServerSnapshot
        The complete server snapshot to filter

    Returns
    -------
    ServerSnapshot
        A filtered snapshot with only active components
    """

    def is_active(
        obj: SnapshotType,
    ) -> bool:
        """Return True if the object is active."""
        if isinstance(obj, PaneSnapshot):
            return getattr(obj, "pane_active", "0") == "1"
        if isinstance(obj, WindowSnapshot):
            return getattr(obj, "window_active", "0") == "1"
        return isinstance(obj, (ServerSnapshot, SessionSnapshot))

    filtered = filter_snapshot(full_snapshot, is_active)
    if filtered is None:
        error_msg = "No active objects found!"
        raise ValueError(error_msg)
    return t.cast(ServerSnapshot, filtered)
