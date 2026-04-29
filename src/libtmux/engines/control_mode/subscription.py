"""User-facing subscription handle for tmux ``refresh-client -B``.

A :class:`Subscription` is the return type of
:meth:`libtmux.Server.subscribe`. It owns a bounded
:class:`queue.Queue` populated by the control-mode reader thread
whenever tmux emits a ``%subscription-changed`` event whose name
matches.

Threading model
---------------

* The reader thread (engine-side) calls :meth:`_deliver` to push
  values. Drop-oldest semantics mean the reader never blocks; the
  newest value always wins because the server only emits on change.
* The user thread calls ``subscription.queue.get(timeout=…)`` to
  consume values. Standard :class:`queue.Queue` thread-safety
  applies — any number of threads can drain.
* :meth:`unsubscribe` is idempotent and safe from any thread.
"""

from __future__ import annotations

import contextlib
import logging
import queue
import threading
import typing as t
import weakref
from dataclasses import dataclass, field

if t.TYPE_CHECKING:
    from libtmux.engines.control_mode.base import ControlModeEngine

logger = logging.getLogger(__name__)


_DEFAULT_MAXSIZE = 128


@dataclass
class Subscription:
    """Server-side subscription handle backed by a bounded value queue.

    Parameters
    ----------
    name : str
        Subscription identifier. Must not contain ``:`` because tmux's
        own parser splits on colons (``cmd-refresh-client.c:54``).
    fmt : str
        tmux format string (e.g. ``"#{pane_pwd}"``,
        ``"#{pane_width}x#{pane_height}"``).
    target : str or None
        Subscription target shape:

        * ``None`` — session-wide (``CONTROL_SUB_SESSION``)
        * ``"%*"`` — all panes
        * ``"%<id>"`` — a specific pane
        * ``"@*"`` — all windows
        * ``"@<id>"`` — a specific window

    queue : queue.Queue[str]
        Bounded queue receiving the expanded format value as a string
        every time it changes server-side. Drop-oldest under pressure.
    """

    name: str
    fmt: str
    target: str | None
    queue: queue.Queue[str]
    _engine_ref: weakref.ref[ControlModeEngine] | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _closed: bool = False

    def __post_init__(self) -> None:
        """Validate ``name`` immediately so misuse is caught at construction."""
        if ":" in self.name:
            msg = (
                "Subscription name cannot contain ':' — tmux parses "
                "refresh-client -B as `name:target:fmt`"
            )
            raise ValueError(msg)

    def unsubscribe(self) -> None:
        """Stop receiving values; idempotent.

        Sends ``refresh-client -B <name>`` (no colons → tmux interprets
        as unsubscribe per ``cmd-refresh-client.c:55``) and removes the
        local routing entry. Errors during the unsubscribe wire call
        are suppressed: an unsubscribe should never fail if the server
        already exited or the engine was closed.
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True
        engine = self._engine_ref() if self._engine_ref is not None else None
        if engine is not None:
            engine._unregister_subscription(self)

    def _deliver(self, value: str) -> None:
        """Push *value* onto the queue with drop-oldest semantics.

        Called by the engine's reader thread. Never blocks: when the
        queue is full, drops the oldest entry first. Justified by
        tmux only emitting ``%subscription-changed`` when the value
        differs from the previous one — old values are stale by
        construction.
        """
        if self._closed:
            return
        try:
            self.queue.put_nowait(value)
        except queue.Full:
            with contextlib.suppress(queue.Empty):
                self.queue.get_nowait()
            try:
                self.queue.put_nowait(value)
            except queue.Full:
                logger.debug(
                    "subscription queue dropped a value under pressure",
                    extra={"tmux_cm_subscription": self.name},
                )

    @property
    def closed(self) -> bool:
        """Whether :meth:`unsubscribe` has been called."""
        with self._lock:
            return self._closed


__all__ = (
    "_DEFAULT_MAXSIZE",
    "Subscription",
)
