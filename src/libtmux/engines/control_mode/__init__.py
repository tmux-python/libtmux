"""Persistent ``tmux -CC`` control-mode engine for libtmux.

The control-mode engine reuses one long-lived ``tmux`` child for every
command, eliminating the per-call ``fork``/``exec``/socket-handshake cost
that dominates the subprocess and one-shot imsg paths.

This module currently exposes a *registration stub*: the engine is known
to :func:`libtmux.engines.create_engine` and ``LIBTMUX_ENGINE=control_mode``
resolves to it, but :meth:`ControlModeEngine.run` raises
:class:`NotImplementedError` until the parser, reader thread, and
subscription wiring land in subsequent steps.
"""

from __future__ import annotations

from libtmux.engines.control_mode.base import (
    ControlModeEngine,
    TmuxControlModeError,
)
from libtmux.engines.control_mode.parser import (
    Block,
    ClientDetachedNotification,
    ClientSessionChangedNotification,
    ContinueNotification,
    ControlParser,
    Event,
    ExitNotification,
    ExtendedOutputNotification,
    MessageNotification,
    Notification,
    OutputNotification,
    PaneModeChangedNotification,
    PasteBufferChangedNotification,
    PasteBufferDeletedNotification,
    PauseNotification,
    SessionChangedNotification,
    SessionRenamedNotification,
    SessionsChangedNotification,
    SessionWindowChangedNotification,
    SubscriptionChangedNotification,
    UnknownNotification,
    UnlinkedWindowAddNotification,
    UnlinkedWindowCloseNotification,
    UnlinkedWindowRenamedNotification,
    WindowAddNotification,
    WindowCloseNotification,
    WindowPaneChangedNotification,
    WindowRenamedNotification,
    unescape_octal,
)
from libtmux.engines.control_mode.subscription import Subscription

__all__ = (
    "Block",
    "ClientDetachedNotification",
    "ClientSessionChangedNotification",
    "ContinueNotification",
    "ControlModeEngine",
    "ControlParser",
    "Event",
    "ExitNotification",
    "ExtendedOutputNotification",
    "MessageNotification",
    "Notification",
    "OutputNotification",
    "PaneModeChangedNotification",
    "PasteBufferChangedNotification",
    "PasteBufferDeletedNotification",
    "PauseNotification",
    "SessionChangedNotification",
    "SessionRenamedNotification",
    "SessionWindowChangedNotification",
    "SessionsChangedNotification",
    "Subscription",
    "SubscriptionChangedNotification",
    "TmuxControlModeError",
    "UnknownNotification",
    "UnlinkedWindowAddNotification",
    "UnlinkedWindowCloseNotification",
    "UnlinkedWindowRenamedNotification",
    "WindowAddNotification",
    "WindowCloseNotification",
    "WindowPaneChangedNotification",
    "WindowRenamedNotification",
    "unescape_octal",
)
