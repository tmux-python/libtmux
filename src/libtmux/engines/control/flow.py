"""Flow control for one pane's output: watermarks, pauses and gaps.

A control-mode client receives a pane's output as fast as the pane produces it.
A consumer that falls behind has two bad options: queue without bound, or drop
output without saying so. :class:`Watermark` does neither. It keeps a bounded
queue; at the *high* mark it asks the driver to pause the pane
(``refresh-client -A %p:pause``), and once the consumer has drained to the *low*
mark it asks for ``:continue``. tmux discards what the pane prints while it is
paused and resumes at the pane's current position, so the stream is told, in
order, that bytes are missing: a :class:`Gap` sits between the last bytes before
the pause and the first bytes after the resume.

This module is I/O-free. It holds no connection and sends nothing: each method
returns the :class:`Action` the driver should take, and the driver reports back
when tmux has acted.
"""

from __future__ import annotations

import collections
import enum
import typing as t
from dataclasses import dataclass


@dataclass(frozen=True)
class Gap:
    """Output was discarded between the previous item and the next one.

    A consumer that needs every byte resynchronises here, for example by
    reading the pane's screen with ``capture_since``.

    Attributes
    ----------
    pane : str
        The pane id, such as ``%3``.

    Examples
    --------
    >>> Gap("%3")
    Gap(pane='%3')
    """

    pane: str


class Action(enum.Enum):
    """What the driver should send to tmux next."""

    PAUSE = "pause"
    CONTINUE = "continue"


class _State(enum.Enum):
    FLOWING = "flowing"
    PAUSE_REQUESTED = "pause-requested"
    PAUSED = "paused"
    CONTINUE_REQUESTED = "continue-requested"


class Watermark:
    """A bounded queue of one pane's output with pause and resume at its marks.

    Parameters
    ----------
    pane : str
        The pane id; stamped on every :class:`Gap`.
    high : int
        Queued bytes at which the pane is paused.
    low : int
        Queued bytes at or below which a paused pane is resumed.

    Raises
    ------
    ValueError
        *low* is negative or *high* is not greater than *low*.

    Examples
    --------
    A producer that outruns its consumer is paused at the high mark, and the
    stream says so with a gap:

    >>> buf = Watermark("%1", high=10, low=4)
    >>> buf.push(b"12345")
    >>> buf.push(b"67890")
    <Action.PAUSE: 'pause'>
    >>> buf.pause_took_effect()
    >>> buf.pop()
    (b'12345', None)

    Draining to the low mark resumes the pane. The gap stays queued, so the
    consumer still sees it before the bytes that follow the pause:

    >>> buf.pop()
    (b'67890', <Action.CONTINUE: 'continue'>)
    >>> buf.continue_took_effect()
    >>> buf.push(b"more")
    >>> buf.pop()
    (Gap(pane='%1'), None)
    >>> buf.pop()
    (b'more', None)
    """

    def __init__(self, pane: str, *, high: int, low: int) -> None:
        if low < 0 or high <= low:
            msg = f"watermarks need 0 <= low < high, got low={low} high={high}"
            raise ValueError(msg)
        self.pane = pane
        self.high = high
        self.low = low
        self._items: collections.deque[bytes | Gap] = collections.deque()
        self._queued = 0
        self._state = _State.FLOWING
        self._closed = False
        self.peak = 0
        self.gaps = 0

    @property
    def queued(self) -> int:
        """Bytes waiting for the consumer."""
        return self._queued

    @property
    def closed(self) -> bool:
        """Whether no more output will arrive."""
        return self._closed

    @property
    def paused(self) -> bool:
        """Whether a pause is requested or in effect."""
        return self._state is not _State.FLOWING

    def __bool__(self) -> bool:
        """Whether an item is ready to pop."""
        return bool(self._items)

    def push(self, data: bytes) -> Action | None:
        """Queue output; return :attr:`Action.PAUSE` when it crosses the high mark.

        Bytes that were already in flight when a pause was requested still
        arrive and are queued: tmux's reply to the pause marks where it took
        effect.
        """
        if self._closed or not data:
            return None
        self._items.append(data)
        self._queued += len(data)
        self.peak = max(self.peak, self._queued)
        if self._state is _State.FLOWING and self._queued >= self.high:
            self._state = _State.PAUSE_REQUESTED
            return Action.PAUSE
        return None

    def pause_took_effect(self) -> Action | None:
        """Record that tmux began discarding; queue the gap.

        Also the answer to a pause tmux started itself (``pause-after``), which
        needs a gap and a resume just the same.

        Returns :attr:`Action.CONTINUE` when the consumer had already drained
        below the low mark, so the pane is not left paused with nobody to
        resume it.
        """
        if self._state not in (_State.PAUSE_REQUESTED, _State.FLOWING):
            return None
        self._items.append(Gap(self.pane))
        self.gaps += 1
        self._state = _State.PAUSED
        return self._resume_if_drained()

    def continue_took_effect(self) -> None:
        """Record that tmux resumed sending output."""
        if self._state is _State.CONTINUE_REQUESTED:
            self._state = _State.FLOWING

    def lost(self) -> None:
        """Record that output was lost with the connection; queue a gap.

        A new connection starts flowing, so any pause is forgotten.
        """
        if self._closed:
            return
        if not self._items or not isinstance(self._items[-1], Gap):
            self._items.append(Gap(self.pane))
            self.gaps += 1
        self._state = _State.FLOWING

    def pop(self) -> tuple[bytes | Gap | None, Action | None]:
        """Take the next item, and the action draining it calls for.

        Returns
        -------
        tuple
            The item, or ``None`` when empty, and :attr:`Action.CONTINUE` when
            this pop drained a paused pane to the low mark.
        """
        if not self._items:
            return None, None
        item = self._items.popleft()
        if isinstance(item, bytes):
            self._queued -= len(item)
        return item, self._resume_if_drained()

    def close(self) -> None:
        """Mark the stream ended; queued items remain poppable."""
        self._closed = True

    def _resume_if_drained(self) -> Action | None:
        if self._state is _State.PAUSED and self._queued <= self.low:
            self._state = _State.CONTINUE_REQUESTED
            return Action.CONTINUE
        return None


__all__: t.Final = ("Action", "Gap", "Watermark")
