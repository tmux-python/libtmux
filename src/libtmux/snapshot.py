"""Hierarchical snapshots of tmux objects.

libtmux.snapshot
~~~~~~~~~~~~~~

- **License**: MIT
- **Description**: Snapshot data structure for tmux objects

Note on type checking:
  The snapshot classes intentionally override properties from parent classes with
  slightly different return types (covariant types - e.g., returning WindowSnapshot
  instead of Window). This is type-safe at runtime but causes mypy warnings. We use
  type: ignore[override] comments on these properties and add proper typing.

  Similarly, the seal() methods are implemented by the frozen_dataclass_sealable
  decorator at runtime but not visible to mypy's static analysis.
"""

from __future__ import annotations

import contextlib
import copy
import datetime
import typing as t
from dataclasses import field

from typing_extensions import Self

from libtmux._internal.frozen_dataclass_sealable import frozen_dataclass_sealable
from libtmux._internal.query_list import QueryList
from libtmux.pane import Pane
from libtmux.server import Server
from libtmux.session import Session
from libtmux.window import Window

if t.TYPE_CHECKING:
    from types import TracebackType

    PaneT = t.TypeVar("PaneT", bound=Pane, covariant=True)
    WindowT = t.TypeVar("WindowT", bound=Window, covariant=True)
    SessionT = t.TypeVar("SessionT", bound=Session, covariant=True)
    ServerT = t.TypeVar("ServerT", bound=Server, covariant=True)


@frozen_dataclass_sealable
class PaneSnapshot(Pane):
    """A read-only snapshot of a tmux pane.

    This maintains compatibility with the original Pane class but prevents
    modification.
    """

    pane_content: list[str] | None = None
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    window_snapshot: WindowSnapshot | None = field(
        default=None,
        metadata={"mutable_during_init": True},
    )

    def __enter__(self) -> Self:
        """Context manager entry point."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit point."""

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
    def window(self) -> WindowSnapshot | None:  # type: ignore[override]
        """Return the window this pane belongs to."""
        return self.window_snapshot

    @property
    def session(self) -> SessionSnapshot | None:  # type: ignore[override]
        """Return the session this pane belongs to."""
        return self.window_snapshot.session_snapshot if self.window_snapshot else None

    def seal(self, deep: bool = False) -> None:  # type: ignore[attr-defined]
        """Seal the snapshot.

        Parameters
        ----------
        deep : bool, optional
            Recursively seal nested sealable objects, by default False
        """
        super().seal(deep=deep)

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
        pane_content = None
        if capture_content:
            with contextlib.suppress(Exception):
                pane_content = pane.capture_pane()

        snapshot = cls(server=pane.server)

        for name, value in vars(pane).items():
            if not name.startswith("_"):  # Skip private attributes
                object.__setattr__(snapshot, name, copy.deepcopy(value))

        object.__setattr__(snapshot, "pane_content", pane_content)
        object.__setattr__(snapshot, "window_snapshot", window_snapshot)
        object.__setattr__(snapshot, "created_at", datetime.datetime.now())

        snapshot.seal()

        return snapshot


@frozen_dataclass_sealable
class WindowSnapshot(Window):
    """A read-only snapshot of a tmux window.

    This maintains compatibility with the original Window class but prevents
    modification.
    """

    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    session_snapshot: SessionSnapshot | None = field(
        default=None,
        metadata={"mutable_during_init": True},
    )
    panes_snapshot: list[PaneSnapshot] = field(
        default_factory=list,
        metadata={"mutable_during_init": True},
    )

    def __enter__(self) -> Self:
        """Context manager entry point."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit point."""

    def cmd(self, *args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        """Prevent executing tmux commands on a snapshot."""
        error_msg = "WindowSnapshot is read-only and cannot execute tmux commands"
        raise NotImplementedError(error_msg)

    @property
    def panes(self) -> QueryList[PaneSnapshot]:  # type: ignore[override]
        """Return the list of panes in this window."""
        return QueryList(self.panes_snapshot)

    @property
    def session(self) -> SessionSnapshot | None:  # type: ignore[override]
        """Return the session this window belongs to."""
        return self.session_snapshot

    @property
    def active_pane(self) -> PaneSnapshot | None:
        """Return the active pane from the pane snapshots."""
        active_panes = [
            p for p in self.panes_snapshot if getattr(p, "pane_active", "0") == "1"
        ]
        return active_panes[0] if active_panes else None

    def seal(self, deep: bool = False) -> None:  # type: ignore[attr-defined]
        """Seal the snapshot.

        Parameters
        ----------
        deep : bool, optional
            Recursively seal nested sealable objects, by default False
        """
        super().seal(deep=deep)

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
        snapshot = cls(server=window.server)

        for name, value in vars(window).items():
            if not name.startswith("_"):  # Skip private attributes
                object.__setattr__(snapshot, name, copy.deepcopy(value))

        object.__setattr__(snapshot, "created_at", datetime.datetime.now())
        object.__setattr__(snapshot, "session_snapshot", session_snapshot)

        panes_snapshot = []
        for pane in window.panes:
            pane_snapshot = PaneSnapshot.from_pane(
                pane,
                capture_content=capture_content,
                window_snapshot=snapshot,
            )
            panes_snapshot.append(pane_snapshot)
        object.__setattr__(snapshot, "panes_snapshot", panes_snapshot)

        snapshot.seal()

        return snapshot


@frozen_dataclass_sealable
class SessionSnapshot(Session):
    """A read-only snapshot of a tmux session.

    This maintains compatibility with the original Session class but prevents
    modification.
    """

    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    server_snapshot: ServerSnapshot | None = field(
        default=None,
        metadata={"mutable_during_init": True},
    )
    windows_snapshot: list[WindowSnapshot] = field(
        default_factory=list,
        metadata={"mutable_during_init": True},
    )

    def __enter__(self) -> Self:
        """Context manager entry point."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit point."""

    def cmd(self, *args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        """Prevent executing tmux commands on a snapshot."""
        error_msg = "SessionSnapshot is read-only and cannot execute tmux commands"
        raise NotImplementedError(error_msg)

    @property
    def windows(self) -> QueryList[WindowSnapshot]:  # type: ignore[override]
        """Return the list of windows in this session."""
        return QueryList(self.windows_snapshot)

    @property
    def server(self) -> ServerSnapshot | None:  # type: ignore[override]
        """Return the server this session belongs to."""
        return self.server_snapshot

    @property
    def active_window(self) -> WindowSnapshot | None:  # type: ignore[override]
        """Return the active window in this session."""
        for window in self.windows_snapshot:
            if getattr(window, "window_active", "0") == "1":
                return window
        return None if not self.windows_snapshot else self.windows_snapshot[0]

    @property
    def active_pane(self) -> PaneSnapshot | None:
        """Return the active pane from the active window, if it exists."""
        active_win = self.active_window
        return active_win.active_pane if active_win else None

    def seal(self, deep: bool = False) -> None:  # type: ignore[attr-defined]
        """Seal the snapshot.

        Parameters
        ----------
        deep : bool, optional
            Recursively seal nested sealable objects, by default False
        """
        super().seal(deep=deep)

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
        snapshot = cls(server=session.server)

        for name, value in vars(session).items():
            if not name.startswith("_"):  # Skip private attributes
                object.__setattr__(snapshot, name, copy.deepcopy(value))

        object.__setattr__(snapshot, "created_at", datetime.datetime.now())
        object.__setattr__(snapshot, "server_snapshot", server_snapshot)

        windows_snapshot = []
        for window in session.windows:
            window_snapshot = WindowSnapshot.from_window(
                window,
                capture_content=capture_content,
                session_snapshot=snapshot,
            )
            windows_snapshot.append(window_snapshot)
        object.__setattr__(snapshot, "windows_snapshot", windows_snapshot)

        snapshot.seal()

        return snapshot


@frozen_dataclass_sealable
class ServerSnapshot(Server):
    """A read-only snapshot of a tmux server.

    This maintains compatibility with the original Server class but prevents
    modification.
    """

    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    sessions_snapshot: list[SessionSnapshot] = field(
        default_factory=list,
        metadata={"mutable_during_init": True},
    )
    windows_snapshot: list[WindowSnapshot] = field(
        default_factory=list,
        metadata={"mutable_during_init": True},
    )
    panes_snapshot: list[PaneSnapshot] = field(
        default_factory=list,
        metadata={"mutable_during_init": True},
    )

    def __enter__(self) -> Self:
        """Context manager entry point."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit point."""

    def cmd(self, *args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        """Prevent executing tmux commands on a snapshot."""
        error_msg = "ServerSnapshot is read-only and cannot execute tmux commands"
        raise NotImplementedError(error_msg)

    def is_alive(self) -> bool:
        """Return False as snapshot servers are not connected to live tmux."""
        return False

    def raise_if_dead(self) -> None:
        """Raise exception as snapshots are not connected to a live server."""
        error_msg = "ServerSnapshot is not connected to a live tmux server"
        raise ConnectionError(error_msg)

    @property
    def sessions(self) -> QueryList[SessionSnapshot]:  # type: ignore[override]
        """Return the list of sessions on this server."""
        return QueryList(self.sessions_snapshot)

    @property
    def windows(self) -> QueryList[WindowSnapshot]:  # type: ignore[override]
        """Return the list of windows on this server."""
        return QueryList(self.windows_snapshot)

    @property
    def panes(self) -> QueryList[PaneSnapshot]:  # type: ignore[override]
        """Return the list of panes on this server."""
        return QueryList(self.panes_snapshot)

    def seal(self, deep: bool = False) -> None:  # type: ignore[attr-defined]
        """Seal the snapshot.

        Parameters
        ----------
        deep : bool, optional
            Recursively seal nested sealable objects, by default False
        """
        super().seal(deep=deep)

    @classmethod
    def from_server(
        cls,
        server: Server,
        include_content: bool = True,
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
        snapshot = cls()

        for name, value in vars(server).items():
            if not name.startswith("_") and name not in {
                "sessions",
                "windows",
                "panes",
            }:
                object.__setattr__(snapshot, name, copy.deepcopy(value))

        object.__setattr__(snapshot, "created_at", datetime.datetime.now())

        sessions_snapshot = []
        windows_snapshot = []
        panes_snapshot = []

        for session in server.sessions:
            session_snapshot = SessionSnapshot.from_session(
                session,
                capture_content=include_content,
                server_snapshot=snapshot,
            )
            sessions_snapshot.append(session_snapshot)

            for window in session_snapshot.windows:
                windows_snapshot.append(window)
                # Extend the panes_snapshot list with all panes from the window
                panes_snapshot.extend(window.panes_snapshot)

        object.__setattr__(snapshot, "sessions_snapshot", sessions_snapshot)
        object.__setattr__(snapshot, "windows_snapshot", windows_snapshot)
        object.__setattr__(snapshot, "panes_snapshot", panes_snapshot)

        snapshot.seal()

        return snapshot


def filter_snapshot(
    snapshot: ServerSnapshot | SessionSnapshot | WindowSnapshot | PaneSnapshot,
    filter_func: t.Callable[
        [ServerSnapshot | SessionSnapshot | WindowSnapshot | PaneSnapshot],
        bool,
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
    if isinstance(snapshot, ServerSnapshot):
        filtered_sessions = []

        for sess in snapshot.sessions_snapshot:
            session_copy = filter_snapshot(sess, filter_func)
            if session_copy is not None:
                filtered_sessions.append(t.cast(SessionSnapshot, session_copy))

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
        filtered_windows = []

        for w in snapshot.windows_snapshot:
            window_copy = filter_snapshot(w, filter_func)
            if window_copy is not None:
                filtered_windows.append(t.cast(WindowSnapshot, window_copy))

        if not filter_func(snapshot) and not filtered_windows:
            return None

        session_copy = copy.deepcopy(snapshot)
        object.__setattr__(session_copy, "windows_snapshot", filtered_windows)
        return session_copy

    if isinstance(snapshot, WindowSnapshot):
        filtered_panes = []

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
        obj: ServerSnapshot | SessionSnapshot | WindowSnapshot | PaneSnapshot,
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
    return t.cast("ServerSnapshot", filtered)
