"""Base classes for snapshot objects.

This module contains base classes that implement sealable behavior for
tmux objects (Server, Session, Window, Pane).
"""

from __future__ import annotations

import typing as t

from libtmux._internal.frozen_dataclass_sealable import Sealable
from libtmux._internal.query_list import QueryList
from libtmux.pane import Pane
from libtmux.server import Server
from libtmux.session import Session
from libtmux.snapshot.types import PaneT, SessionT, WindowT
from libtmux.window import Window

# Forward references
if t.TYPE_CHECKING:
    from libtmux.snapshot.models.server import ServerSnapshot
    from libtmux.snapshot.types import SnapshotType


class SnapshotBase(Sealable):
    """Base class for all snapshot classes.

    This class provides common methods for all snapshot classes, such as filtering
    and serialization to dictionary.
    """

    _is_snapshot: bool = True

    def to_dict(self) -> dict[str, t.Any]:
        """Convert the snapshot to a dictionary.

        This is useful for serializing snapshots to JSON or other formats.

        Returns
        -------
        dict[str, t.Any]
            A dictionary representation of the snapshot

        Examples
        --------
        >>> from libtmux import Server
        >>> from libtmux.snapshot.factory import create_snapshot
        >>> server = Server()
        >>> snapshot = create_snapshot(server)
        >>> data = snapshot.to_dict()
        >>> isinstance(data, dict)
        True
        """
        from libtmux.snapshot.utils import snapshot_to_dict

        return snapshot_to_dict(self)

    def filter(
        self, filter_func: t.Callable[[SnapshotType], bool]
    ) -> SnapshotType | None:
        """Filter the snapshot tree based on a filter function.

        This recursively filters the snapshot tree based on the filter function.
        Parent-child relationships are maintained in the filtered snapshot.

        Parameters
        ----------
        filter_func : Callable[[SnapshotType], bool]
            A function that takes a snapshot object and returns True to keep it
            or False to filter it out

        Returns
        -------
        Optional[SnapshotType]
            A new filtered snapshot, or None if everything was filtered out

        Examples
        --------
        >>> from libtmux import Server
        >>> from libtmux.snapshot.factory import create_snapshot
        >>> server = Server()
        >>> snapshot = create_snapshot(server)
        >>> # Filter to include only objects with 'name' attribute
        >>> filtered = snapshot.filter(lambda x: hasattr(x, 'name'))
        """
        from libtmux.snapshot.utils import filter_snapshot

        # This is safe at runtime because concrete implementations will
        # satisfy the type constraints
        return filter_snapshot(self, filter_func)  # type: ignore[arg-type]

    def active_only(self) -> ServerSnapshot | None:
        """Filter the snapshot to include only active components.

        This is a convenience method that filters the snapshot to include only
        active sessions, windows, and panes.

        Returns
        -------
        Optional[ServerSnapshot]
            A new filtered snapshot containing only active components, or None if
            there are no active components

        Examples
        --------
        >>> from libtmux import Server
        >>> from libtmux.snapshot.factory import create_snapshot
        >>> server = Server()
        >>> snapshot = create_snapshot(server)
        >>> active = snapshot.active_only()

        Raises
        ------
        NotImplementedError
            If called on a snapshot that is not a ServerSnapshot
        """
        # Only implement for ServerSnapshot
        if not hasattr(self, "sessions_snapshot"):
            cls_name = type(self).__name__
            msg = f"active_only() is only supported for ServerSnapshot, not {cls_name}"
            raise NotImplementedError(msg)

        from libtmux.snapshot.utils import snapshot_active_only

        try:
            # This is safe at runtime because we check for the
            # sessions_snapshot attribute
            return snapshot_active_only(self)  # type: ignore[arg-type]
        except ValueError:
            return None


class SealablePaneBase(Pane, SnapshotBase):
    """Base class for sealable pane classes."""


class SealableWindowBase(Window, SnapshotBase, t.Generic[PaneT]):
    """Base class for sealable window classes with generic pane type."""

    @property
    def panes(self) -> QueryList[PaneT]:
        """Return panes with the appropriate generic type."""
        return t.cast(QueryList[PaneT], super().panes)

    @property
    def active_pane(self) -> PaneT | None:
        """Return active pane with the appropriate generic type."""
        return t.cast(t.Optional[PaneT], super().active_pane)


class SealableSessionBase(Session, SnapshotBase, t.Generic[WindowT, PaneT]):
    """Base class for sealable session classes with generic window and pane types."""

    @property
    def windows(self) -> QueryList[WindowT]:
        """Return windows with the appropriate generic type."""
        return t.cast(QueryList[WindowT], super().windows)

    @property
    def active_window(self) -> WindowT | None:
        """Return active window with the appropriate generic type."""
        return t.cast(t.Optional[WindowT], super().active_window)

    @property
    def active_pane(self) -> PaneT | None:
        """Return active pane with the appropriate generic type."""
        return t.cast(t.Optional[PaneT], super().active_pane)


class SealableServerBase(Server, SnapshotBase, t.Generic[SessionT, WindowT, PaneT]):
    """Generic base for sealable server with typed session, window, and pane."""

    @property
    def sessions(self) -> QueryList[SessionT]:
        """Return sessions with the appropriate generic type."""
        return t.cast(QueryList[SessionT], super().sessions)

    @property
    def windows(self) -> QueryList[WindowT]:
        """Return windows with the appropriate generic type."""
        return t.cast(QueryList[WindowT], super().windows)

    @property
    def panes(self) -> QueryList[PaneT]:
        """Return panes with the appropriate generic type."""
        return t.cast(QueryList[PaneT], super().panes)
