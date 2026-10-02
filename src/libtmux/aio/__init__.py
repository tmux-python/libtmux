"""asyncio API: streaming pane output, incremental capture and waits.

Everything here takes an :class:`~libtmux.engines.base.AsyncTmuxEngine` and
nothing blocks the event loop. Cancelling any awaitable leaves no tmux process
and no pending reply behind.

- :class:`~libtmux.aio.stream.PaneStream` yields a pane's output as ``bytes``
  and :class:`~libtmux.aio.stream.Gap`.
- :func:`~libtmux.aio.capture.capture_since` and
  :func:`~libtmux.aio.capture.wait_for_text` are the awaitable forms of the
  blocking :meth:`Pane.capture_since() <libtmux.Pane.capture_since>` and
  :meth:`Pane.wait_for_text() <libtmux.Pane.wait_for_text>`.
"""

from __future__ import annotations

from libtmux.aio.capture import capture_since, wait_for_text
from libtmux.aio.stream import Gap, PaneStream

__all__ = ("Gap", "PaneStream", "capture_since", "wait_for_text")
