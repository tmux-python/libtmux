"""Pure, immutable snapshots of the tmux object graph.

A neo-like view of server/session/window/pane state as plain *values* -- no live
:class:`~libtmux.Server`, no command dispatch, no coupling to the existing ORM or
query pipeline. Snapshots are immutable, composable into a tree, and serializable,
so they are safe to experiment with under :mod:`libtmux.experimental` without
touching shipped APIs. See the operationalization plan (``tmux-python/libtmux``
issue 689).
"""

from __future__ import annotations

from libtmux.experimental.models.snapshots import (
    ClientSnapshot,
    PaneSnapshot,
    ServerSnapshot,
    SessionSnapshot,
    WindowSnapshot,
)

__all__ = (
    "ClientSnapshot",
    "PaneSnapshot",
    "ServerSnapshot",
    "SessionSnapshot",
    "WindowSnapshot",
)
