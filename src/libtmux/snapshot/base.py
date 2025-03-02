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


class SealablePaneBase(Pane, Sealable):
    """Base class for sealable pane classes."""


class SealableWindowBase(Window, Sealable, t.Generic[PaneT]):
    """Base class for sealable window classes with generic pane type."""

    @property
    def panes(self) -> QueryList[PaneT]:
        """Return panes with the appropriate generic type."""
        return t.cast(QueryList[PaneT], super().panes)

    @property
    def active_pane(self) -> PaneT | None:
        """Return active pane with the appropriate generic type."""
        return t.cast(t.Optional[PaneT], super().active_pane)


class SealableSessionBase(Session, Sealable, t.Generic[WindowT, PaneT]):
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


class SealableServerBase(Server, Sealable, t.Generic[SessionT, WindowT, PaneT]):
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
