"""Hierarchical snapshots of tmux objects.

libtmux.snapshot
~~~~~~~~~~~~~~~~

This module provides read-only snapshot classes for tmux objects that preserve
the object structure and relationships while preventing modifications or
tmux command execution.
"""

from __future__ import annotations

import contextlib
import copy
import typing as t
from dataclasses import field
from datetime import datetime
from types import TracebackType

from libtmux._internal.frozen_dataclass_sealable import frozen_dataclass_sealable
from libtmux._internal.query_list import QueryList
from libtmux.pane import Pane
from libtmux.server import Server
from libtmux.session import Session
from libtmux.window import Window

if t.TYPE_CHECKING:
    pass


@frozen_dataclass_sealable
class PaneSnapshot(Pane):
    """A read-only snapshot of a tmux pane.

    This maintains compatibility with the original Pane class but prevents modification.
    """

    # Fields only present in snapshot
    pane_content: list[str] | None = None
    created_at: datetime = field(default_factory=datetime.now)
    window_snapshot: WindowSnapshot | None = field(
        default=None, metadata={"mutable_during_init": True}
    )

    def __enter__(self) -> PaneSnapshot:
        """Context manager entry point."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit point."""
        pass

    def cmd(self, *args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        """Prevent executing tmux commands on a snapshot."""
        error_msg = "PaneSnapshot is read-only and cannot execute tmux commands"
        raise NotImplementedError(error_msg)

    def capture_pane(self, *args: t.Any, **kwargs: t.Any) -> list[str]:
        """Return the previously captured content instead of capturing new content."""
        if self.pane_content is None:
            return []
        return self.pane_content

    @property
    def window(self) -> WindowSnapshot | None:
        """Return the WindowSnapshot parent, or None."""
        return self.window_snapshot

    @property
    def session(self) -> SessionSnapshot | None:
        """Return SessionSnapshot via window_snapshot's session_snapshot, or None."""
        if self.window_snapshot is not None:
            return self.window_snapshot.session_snapshot
        return None

    @classmethod
    def from_pane(
        cls,
        pane: Pane,
        capture_content: bool = True,
        window_snapshot: WindowSnapshot | None = None,
    ) -> PaneSnapshot:
        """Create a PaneSnapshot from a live Pane.

        Parameters
        ----------
        pane : Pane
            Live pane to snapshot
        capture_content : bool, optional
            Whether to capture the current text from the pane
        window_snapshot : WindowSnapshot, optional
            Parent window snapshot to link back to

        Returns
        -------
        PaneSnapshot
            A read-only snapshot of the pane
        """
        # Try capturing the pane's content
        pane_content = None
        if capture_content:
            with contextlib.suppress(Exception):
                pane_content = pane.capture_pane()

        # Create a new snapshot instance
        snapshot = cls(server=pane.server)

        # Copy all relevant attributes from the original pane
        for name, value in vars(pane).items():
            if not name.startswith("_"):  # Skip private attributes
                object.__setattr__(snapshot, name, copy.deepcopy(value))

        # Set snapshot-specific fields
        object.__setattr__(snapshot, "pane_content", pane_content)
        object.__setattr__(snapshot, "window_snapshot", window_snapshot)
        object.__setattr__(snapshot, "created_at", datetime.now())

        # Seal the snapshot
        snapshot.seal()

        return snapshot


@frozen_dataclass_sealable
class WindowSnapshot(Window):
    """A read-only snapshot of a tmux window.

    This maintains compatibility with the original Window class but prevents modification.
    """

    # Fields only present in snapshot
    created_at: datetime = field(default_factory=datetime.now)
    session_snapshot: SessionSnapshot | None = field(
        default=None, metadata={"mutable_during_init": True}
    )
    panes_snapshot: list[PaneSnapshot] = field(
        default_factory=list, metadata={"mutable_during_init": True}
    )

    def __enter__(self) -> WindowSnapshot:
        """Context manager entry point."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit point."""
        pass

    def cmd(self, *args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        """Prevent executing tmux commands on a snapshot."""
        error_msg = "WindowSnapshot is read-only and cannot execute tmux commands"
        raise NotImplementedError(error_msg)

    @property
    def panes(self) -> QueryList[PaneSnapshot]:
        """Return the list of pane snapshots."""
        return QueryList(self.panes_snapshot)

    @property
    def session(self) -> SessionSnapshot | None:
        """Return the SessionSnapshot parent, or None."""
        return self.session_snapshot

    @property
    def active_pane(self) -> PaneSnapshot | None:
        """Return the active pane from the pane snapshots."""
        active_panes = [
            p for p in self.panes_snapshot if getattr(p, "pane_active", "0") == "1"
        ]
        return active_panes[0] if active_panes else None

    @classmethod
    def from_window(
        cls,
        window: Window,
        capture_content: bool = True,
        session_snapshot: SessionSnapshot | None = None,
    ) -> WindowSnapshot:
        """Create a WindowSnapshot from a live Window.

        Parameters
        ----------
        window : Window
            Live window to snapshot
        capture_content : bool, optional
            Whether to capture the current content of all panes
        session_snapshot : SessionSnapshot, optional
            Parent session snapshot to link back to

        Returns
        -------
        WindowSnapshot
            A read-only snapshot of the window
        """
        # Create the window snapshot first (without panes)
        snapshot = cls(server=window.server)

        # Copy window attributes
        for name, value in vars(window).items():
            if not name.startswith("_"):  # Skip private attributes
                object.__setattr__(snapshot, name, copy.deepcopy(value))

        # Set snapshot-specific fields
        object.__setattr__(snapshot, "created_at", datetime.now())
        object.__setattr__(snapshot, "session_snapshot", session_snapshot)

        # Snapshot panes (after session_snapshot is set to maintain bi-directional links)
        panes_snapshot = []
        for pane in window.panes:
            pane_snapshot = PaneSnapshot.from_pane(
                pane, capture_content=capture_content, window_snapshot=snapshot
            )
            panes_snapshot.append(pane_snapshot)
        object.__setattr__(snapshot, "panes_snapshot", panes_snapshot)

        # Seal the snapshot to prevent further modifications
        snapshot.seal()

        return snapshot


@frozen_dataclass_sealable
class SessionSnapshot(Session):
    """A read-only snapshot of a tmux session.

    This maintains compatibility with the original Session class but prevents modification.
    """

    # Fields only present in snapshot
    created_at: datetime = field(default_factory=datetime.now)
    server_snapshot: ServerSnapshot | None = field(
        default=None, metadata={"mutable_during_init": True}
    )
    windows_snapshot: list[WindowSnapshot] = field(
        default_factory=list, metadata={"mutable_during_init": True}
    )

    def __enter__(self) -> SessionSnapshot:
        """Context manager entry point."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit point."""
        pass

    def cmd(self, *args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        """Prevent executing tmux commands on a snapshot."""
        error_msg = "SessionSnapshot is read-only and cannot execute tmux commands"
        raise NotImplementedError(error_msg)

    @property
    def windows(self) -> QueryList[WindowSnapshot]:
        """Return the list of window snapshots."""
        return QueryList(self.windows_snapshot)

    @property
    def server(self) -> ServerSnapshot | None:
        """Return the ServerSnapshot parent, or None."""
        return self.server_snapshot

    @property
    def active_window(self) -> WindowSnapshot | None:
        """Return the active window snapshot, if any."""
        active_windows = [
            w for w in self.windows_snapshot if getattr(w, "window_active", "0") == "1"
        ]
        return active_windows[0] if active_windows else None

    @property
    def active_pane(self) -> PaneSnapshot | None:
        """Return the active pane from the active window, if it exists."""
        active_win = self.active_window
        return active_win.active_pane if active_win else None

    @classmethod
    def from_session(
        cls,
        session: Session,
        *,
        capture_content: bool = False,
        server_snapshot: ServerSnapshot | None = None,
    ) -> SessionSnapshot:
        """Create a SessionSnapshot from a live Session.

        Parameters
        ----------
        session : Session
            Live session to snapshot
        capture_content : bool, optional
            Whether to capture the current content of all panes
        server_snapshot : ServerSnapshot, optional
            Parent server snapshot to link back to

        Returns
        -------
        SessionSnapshot
            A read-only snapshot of the session
        """
        # Create the session snapshot first (without windows)
        snapshot = cls(server=session.server)

        # Copy session attributes
        for name, value in vars(session).items():
            if not name.startswith("_"):  # Skip private attributes
                object.__setattr__(snapshot, name, copy.deepcopy(value))

        # Set snapshot-specific fields
        object.__setattr__(snapshot, "created_at", datetime.now())
        object.__setattr__(snapshot, "server_snapshot", server_snapshot)

        # Snapshot windows (after server_snapshot is set to maintain bi-directional links)
        windows_snapshot = []
        for window in session.windows:
            window_snapshot = WindowSnapshot.from_window(
                window, capture_content=capture_content, session_snapshot=snapshot
            )
            windows_snapshot.append(window_snapshot)
        object.__setattr__(snapshot, "windows_snapshot", windows_snapshot)

        # Seal the snapshot to prevent further modifications
        snapshot.seal()

        return snapshot


@frozen_dataclass_sealable
class ServerSnapshot(Server):
    """A read-only snapshot of a tmux server.

    This maintains compatibility with the original Server class but prevents modification.
    """

    # Fields only present in snapshot
    created_at: datetime = field(default_factory=datetime.now)
    sessions_snapshot: list[SessionSnapshot] = field(
        default_factory=list, metadata={"mutable_during_init": True}
    )
    windows_snapshot: list[WindowSnapshot] = field(
        default_factory=list, metadata={"mutable_during_init": True}
    )
    panes_snapshot: list[PaneSnapshot] = field(
        default_factory=list, metadata={"mutable_during_init": True}
    )

    def __enter__(self) -> ServerSnapshot:
        """Context manager entry point."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit point."""
        pass

    def cmd(self, *args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        """Prevent executing tmux commands on a snapshot."""
        error_msg = "ServerSnapshot is read-only and cannot execute tmux commands"
        raise NotImplementedError(error_msg)

    def is_alive(self) -> bool:
        """Return False as snapshot servers are not connected to a live tmux instance."""
        return False

    def raise_if_dead(self) -> None:
        """Raise exception as snapshots are not connected to a live server."""
        error_msg = "ServerSnapshot is not connected to a live tmux server"
        raise ConnectionError(error_msg)

    @property
    def sessions(self) -> QueryList[SessionSnapshot]:
        """Return the list of session snapshots."""
        return QueryList(self.sessions_snapshot)

    @property
    def windows(self) -> QueryList[WindowSnapshot]:
        """Return the list of all window snapshots across all sessions."""
        return QueryList(self.windows_snapshot)

    @property
    def panes(self) -> QueryList[PaneSnapshot]:
        """Return the list of all pane snapshots across all windows and sessions."""
        return QueryList(self.panes_snapshot)

    @classmethod
    def from_server(
        cls, server: Server, include_content: bool = True
    ) -> ServerSnapshot:
        """Create a ServerSnapshot from a live Server.

        Parameters
        ----------
        server : Server
            Live server to snapshot
        include_content : bool, optional
            Whether to capture the current content of all panes, by default True

        Returns
        -------
        ServerSnapshot
            A read-only snapshot of the server

        Examples
        --------
        The ServerSnapshot.from_server method creates a snapshot of the server:

        ```python
        server_snap = ServerSnapshot.from_server(server)
        isinstance(server_snap, ServerSnapshot)  # True
        ```
        """
        # Create the server snapshot (without sessions, windows, or panes)
        snapshot = cls()

        # Copy server attributes
        for name, value in vars(server).items():
            if not name.startswith("_") and name not in [
                "sessions",
                "windows",
                "panes",
            ]:
                object.__setattr__(snapshot, name, copy.deepcopy(value))

        # Set snapshot-specific fields
        object.__setattr__(snapshot, "created_at", datetime.now())

        # Snapshot all sessions, windows, and panes
        sessions_snapshot = []
        windows_snapshot = []
        panes_snapshot = []

        # First, snapshot all sessions
        for session in server.sessions:
            session_snapshot = SessionSnapshot.from_session(
                session,
                capture_content=include_content,
                server_snapshot=snapshot,
            )
            sessions_snapshot.append(session_snapshot)

            # Collect window and pane snapshots
            for window in session_snapshot.windows:
                windows_snapshot.append(window)
                for pane in window.panes:
                    panes_snapshot.append(pane)

        # Set all collected snapshots
        object.__setattr__(snapshot, "sessions_snapshot", sessions_snapshot)
        object.__setattr__(snapshot, "windows_snapshot", windows_snapshot)
        object.__setattr__(snapshot, "panes_snapshot", panes_snapshot)

        # Seal the snapshot to prevent further modifications
        snapshot.seal()

        return snapshot


def filter_snapshot(
    snapshot: ServerSnapshot | SessionSnapshot | WindowSnapshot | PaneSnapshot,
    filter_func: t.Callable[
        [ServerSnapshot | SessionSnapshot | WindowSnapshot | PaneSnapshot], bool
    ],
) -> ServerSnapshot | SessionSnapshot | WindowSnapshot | PaneSnapshot | None:
    """Filter a snapshot hierarchy based on a filter function.

    This will prune the snapshot tree, removing any objects that don't match the filter.
    The filter is applied recursively down the hierarchy, and parent-child relationships
    are maintained in the filtered snapshot.

    Parameters
    ----------
    snapshot : ServerSnapshot | SessionSnapshot | WindowSnapshot | PaneSnapshot
        The snapshot to filter
    filter_func : Callable
        A function that takes a snapshot object and returns True to keep it
        or False to filter it out

    Returns
    -------
    ServerSnapshot | SessionSnapshot | WindowSnapshot | PaneSnapshot | None
        A new filtered snapshot, or None if everything was filtered out
    """
    # Handle filtering ServerSnapshot
    if isinstance(snapshot, ServerSnapshot):
        filtered_sessions = []

        # Filter each session
        for sess in snapshot.sessions_snapshot:
            filtered_sess = filter_snapshot(sess, filter_func)
            if filtered_sess is not None:
                filtered_sessions.append(filtered_sess)

        # If the server itself fails filter or everything is filtered out, return None
        if not filter_func(snapshot) and not filtered_sessions:
            return None

        # Create a new server snapshot with filtered sessions
        server_copy = copy.deepcopy(snapshot)
        server_copy.sessions_snapshot = filtered_sessions

        # Also update windows and panes lists to reflect filtered data
        server_copy.windows_snapshot = []
        server_copy.panes_snapshot = []
        for sess in filtered_sessions:
            server_copy.windows_snapshot.extend(sess.windows_snapshot)
            for w in sess.windows_snapshot:
                server_copy.panes_snapshot.extend(w.panes_snapshot)

        return server_copy

    # Handle filtering SessionSnapshot
    elif isinstance(snapshot, SessionSnapshot):
        filtered_windows = []

        # Filter each window
        for w in snapshot.windows_snapshot:
            filtered_w = filter_snapshot(w, filter_func)
            if filtered_w is not None:
                filtered_windows.append(filtered_w)

        # If the session itself fails filter or everything is filtered out, return None
        if not filter_func(snapshot) and not filtered_windows:
            return None

        # Create a new session snapshot with filtered windows
        session_copy = copy.deepcopy(snapshot)
        session_copy.windows_snapshot = filtered_windows
        return session_copy

    # Handle filtering WindowSnapshot
    elif isinstance(snapshot, WindowSnapshot):
        filtered_panes = []

        # Filter each pane - panes are leaf nodes
        filtered_panes = [p for p in snapshot.panes_snapshot if filter_func(p)]

        # If the window itself fails filter or everything is filtered out, return None
        if not filter_func(snapshot) and not filtered_panes:
            return None

        # Create a new window snapshot with filtered panes
        window_copy = copy.deepcopy(snapshot)
        window_copy.panes_snapshot = filtered_panes
        return window_copy

    # Handle filtering PaneSnapshot (leaf node)
    elif isinstance(snapshot, PaneSnapshot):
        if filter_func(snapshot):
            return snapshot
        return None

    # Unhandled type
    return snapshot


def snapshot_to_dict(
    snapshot: ServerSnapshot | SessionSnapshot | WindowSnapshot | PaneSnapshot | t.Any,
) -> dict[str, t.Any]:
    """Convert a snapshot to a dictionary, avoiding circular references.

    This is useful for serializing snapshots to JSON or other formats.

    Parameters
    ----------
    snapshot : ServerSnapshot | SessionSnapshot | WindowSnapshot | PaneSnapshot | Any
        The snapshot to convert to a dictionary

    Returns
    -------
    dict
        A dictionary representation of the snapshot
    """
    # Base case: For non-snapshot objects, just return them directly
    if not isinstance(
        snapshot, (ServerSnapshot, SessionSnapshot, WindowSnapshot, PaneSnapshot)
    ):
        return t.cast(dict[str, t.Any], snapshot)

    # Convert dataclass to dict
    result: dict[str, t.Any] = {}

    # Get all fields from the instance
    for name, value in vars(snapshot).items():
        # Skip internal and parent reference fields - we want a tree, not a graph with cycles
        if name.startswith("_") or name in [
            "server",
            "server_snapshot",
            "session_snapshot",
            "window_snapshot",
        ]:
            continue

        # Handle lists of snapshots
        if (
            isinstance(value, list)
            and value
            and isinstance(
                value[0],
                (ServerSnapshot, SessionSnapshot, WindowSnapshot, PaneSnapshot),
            )
        ):
            result[name] = [snapshot_to_dict(item) for item in value]
        # Handle nested snapshots
        elif isinstance(
            value, (ServerSnapshot, SessionSnapshot, WindowSnapshot, PaneSnapshot)
        ):
            result[name] = snapshot_to_dict(value)
        # Handle QueryList (convert to regular list first)
        elif hasattr(value, "list") and callable(getattr(value, "list", None)):
            try:
                # If it's a QueryList, convert to list of dicts
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
                # If not a QueryList, just use the string representation
                result[name] = str(value)
        # Handle non-serializable objects
        elif isinstance(value, datetime):
            result[name] = str(value)
        # Handle remaining basic types
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
        obj: ServerSnapshot | SessionSnapshot | WindowSnapshot | PaneSnapshot,
    ) -> bool:
        """Return True if the object is active."""
        if isinstance(obj, PaneSnapshot):
            return getattr(obj, "pane_active", "0") == "1"
        elif isinstance(obj, WindowSnapshot):
            return getattr(obj, "window_active", "0") == "1"
        # Servers and sessions are always considered active
        return isinstance(obj, (ServerSnapshot, SessionSnapshot))

    filtered = filter_snapshot(full_snapshot, is_active)
    if filtered is None:
        error_msg = "No active objects found!"
        raise ValueError(error_msg)
    return t.cast(ServerSnapshot, filtered)
