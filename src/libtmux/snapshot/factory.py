"""Factory functions for creating snapshots.

This module provides type-safe factory functions for creating snapshots of tmux objects.
It centralizes snapshot creation and provides a consistent API for creating snapshots
of different tmux objects.
"""

from __future__ import annotations

from typing import overload

from libtmux.pane import Pane
from libtmux.server import Server
from libtmux.session import Session
from libtmux.snapshot.models.pane import PaneSnapshot
from libtmux.snapshot.models.server import ServerSnapshot
from libtmux.snapshot.models.session import SessionSnapshot
from libtmux.snapshot.models.window import WindowSnapshot
from libtmux.window import Window


@overload
def create_snapshot(
    obj: Server, *, capture_content: bool = False
) -> ServerSnapshot: ...


@overload
def create_snapshot(
    obj: Session, *, capture_content: bool = False
) -> SessionSnapshot: ...


@overload
def create_snapshot(
    obj: Window, *, capture_content: bool = False
) -> WindowSnapshot: ...


@overload
def create_snapshot(obj: Pane, *, capture_content: bool = False) -> PaneSnapshot: ...


def create_snapshot(
    obj: Server | Session | Window | Pane, *, capture_content: bool = False
) -> ServerSnapshot | SessionSnapshot | WindowSnapshot | PaneSnapshot:
    """Create a snapshot of a tmux object.

    This is a factory function that creates a snapshot of a tmux object
    based on its type. It provides a consistent interface for creating
    snapshots of different tmux objects.

    Parameters
    ----------
    obj : Server | Session | Window | Pane
        The tmux object to create a snapshot of
    capture_content : bool, optional
        Whether to capture the content of panes, by default False

    Returns
    -------
    ServerSnapshot | SessionSnapshot | WindowSnapshot | PaneSnapshot
        A snapshot of the provided tmux object

    Examples
    --------
    Create a snapshot of a server:

    >>> from libtmux import Server
    >>> server = Server()
    >>> snapshot = create_snapshot(server)
    >>> isinstance(snapshot, ServerSnapshot)
    True

    Create a snapshot of a session:

    >>> # Get an existing session or create a new one with a unique name
    >>> import uuid
    >>> session_name = f"test-{uuid.uuid4().hex[:8]}"
    >>> session = server.new_session(session_name)
    >>> snapshot = create_snapshot(session)
    >>> isinstance(snapshot, SessionSnapshot)
    True

    Create a snapshot with pane content:

    >>> snapshot = create_snapshot(session, capture_content=True)
    >>> isinstance(snapshot, SessionSnapshot)
    True
    """
    if isinstance(obj, Server):
        return ServerSnapshot.from_server(obj, include_content=capture_content)
    elif isinstance(obj, Session):
        return SessionSnapshot.from_session(obj, capture_content=capture_content)
    elif isinstance(obj, Window):
        return WindowSnapshot.from_window(obj, capture_content=capture_content)
    elif isinstance(obj, Pane):
        return PaneSnapshot.from_pane(obj, capture_content=capture_content)
    else:
        # This should never happen due to the type annotations
        obj_type = type(obj).__name__
        msg = f"Unsupported object type: {obj_type}"
        raise TypeError(msg)


def create_snapshot_active(
    server: Server, *, capture_content: bool = False
) -> ServerSnapshot:
    """Create a snapshot containing only active sessions, windows, and panes.

    This is a convenience function that creates a snapshot of a server and then
    filters it to only include active components.

    Parameters
    ----------
    server : Server
        The server to create a snapshot of
    capture_content : bool, optional
        Whether to capture the content of panes, by default False

    Returns
    -------
    ServerSnapshot
        A snapshot containing only active components

    Examples
    --------
    Create a snapshot with only active components:

    >>> from libtmux import Server
    >>> server = Server()
    >>> snapshot = create_snapshot_active(server)
    >>> isinstance(snapshot, ServerSnapshot)
    True
    """
    from libtmux.snapshot.utils import snapshot_active_only

    server_snapshot = create_snapshot(server, capture_content=capture_content)
    return snapshot_active_only(server_snapshot)
