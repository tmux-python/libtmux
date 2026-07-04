"""The live session→window→pane tree, derived from tmux (never the truth).

A thin layer over ``ServerSnapshot.from_pane_rows``: the format to request, a
flattener to a ``{pane_id: PaneSnapshot}`` map, and a diff used by the monitor's
reconcile to synthesize the add/remove events the notification stream missed.
"""

from __future__ import annotations

import typing as t

if t.TYPE_CHECKING:
    from libtmux.experimental.models.snapshots import PaneSnapshot, ServerSnapshot

PANE_FORMAT: tuple[str, ...] = (
    "session_id",
    "session_name",
    "window_id",
    "window_index",
    "window_name",
    "window_active",
    "pane_id",
    "pane_index",
    "pane_active",
    "pane_floating_flag",
    "pane_pid",
    "pane_current_command",
    "pane_title",
    "@agent_state",
    "@agent_name",
)


def panes_of(snapshot: ServerSnapshot) -> dict[str, PaneSnapshot]:
    """Flatten a server snapshot to ``{pane_id: PaneSnapshot}``.

    Parameters
    ----------
    snapshot : ServerSnapshot
        A server snapshot containing sessions, windows, and panes.

    Returns
    -------
    dict[str, PaneSnapshot]
        A dictionary mapping pane IDs to PaneSnapshot objects.

    Examples
    --------
    >>> from libtmux.experimental.models.snapshots import ServerSnapshot
    >>> snap = ServerSnapshot.from_pane_rows(
    ...     [{"session_id": "$0", "window_id": "@0", "pane_id": "%1"}])
    >>> list(panes_of(snap))
    ['%1']
    """
    return {
        pane.pane_id: pane
        for session in snapshot.sessions
        for window in session.windows
        for pane in window.panes
    }


def diff_panes(
    old: dict[str, t.Any], new: dict[str, t.Any]
) -> tuple[list[str], list[str]]:
    """Return ``(added_pane_ids, removed_pane_ids)`` between two pane maps.

    Parameters
    ----------
    old : dict[str, t.Any]
        The old pane map (by pane ID).
    new : dict[str, t.Any]
        The new pane map (by pane ID).

    Returns
    -------
    tuple[list[str], list[str]]
        A tuple of (added_pane_ids, removed_pane_ids).

    Examples
    --------
    >>> diff_panes({"%1": 1, "%2": 1}, {"%2": 1, "%3": 1})
    (['%3'], ['%1'])
    """
    added = [pid for pid in new if pid not in old]
    removed = [pid for pid in old if pid not in new]
    return added, removed
