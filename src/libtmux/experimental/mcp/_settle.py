r"""Needle-free settle accumulator for the pane-output monitor.

A tmux pane stops emitting ``%output`` the instant it stops producing bytes, so
"no ``%output`` for ``settle_ms``" is a direct I/O-layer *quiet* signal -- no
regex, no sentinel injection, no assumed output format. This module is the pure,
framework-free core of that idea: a decoder for tmux's octal ``%output``
escaping, a per-pane payload filter, and a fold over an injected async stream
that returns the moment the stream goes quiet (or a byte/time cap fires).

It imports no MCP framework and touches no tmux connection, so every function
here carries an executable doctest driven by literal strings or a fake async
generator with an injected clock. The :mod:`~.events` edge maps a control-mode
engine's ``subscribe()`` stream onto these helpers.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import typing as t
from dataclasses import dataclass

from libtmux.experimental.engines.base import unescape_control_output

if t.TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from libtmux.experimental.engines.async_control_mode import ControlNotification

SettleReason = t.Literal["settled", "time_cap", "byte_cap", "stream_end"]


@dataclass(frozen=True)
class SettleOutcome:
    """Result of folding a decoded ``%output`` stream until the pane settles.

    Attributes
    ----------
    text : str
        The decoded bytes the pane produced during the watch, with
        tail-preserving truncation when ``truncated``.
    reason : {"settled", "time_cap", "byte_cap", "stream_end"}
        Why the fold stopped. ``settled`` means *stopped producing output*, not
        *succeeded* -- the caller interprets the text.
    byte_count : int
        Size of ``text`` in bytes (capped at ``max_bytes``).
    frame_count : int
        Number of stream chunks folded in.
    idle_ms_observed : int
        Only meaningful when ``reason == "settled"``: the idle gap (``settle_ms``)
        that triggered the stop. For other reasons it is the most recent
        inter-chunk gap, or ``0`` if no chunk arrived -- do not read it as the
        cause of the stop.
    truncated : bool
        Whether ``max_bytes`` clipped the text (tail kept).
    """

    text: str
    reason: SettleReason
    byte_count: int
    frame_count: int
    idle_ms_observed: int
    truncated: bool


def decode_output(payload: str) -> str:
    r"""Decode tmux's backslash-octal ``%output`` escaping.

    Tmux escapes any byte below ``0x20`` and a literal backslash as ``\ooo``
    (exactly three octal digits). Short octal-looking text and a lone trailing
    backslash pass through verbatim rather than being interpreted.

    Parameters
    ----------
    payload : str
        The raw ``%output`` data body, after the ``%output %N `` prefix.

    Returns
    -------
    str
        The decoded text.

    Examples
    --------
    A newline and a tab decode from their octal escapes:

    >>> decode_output('a\\012b')
    'a\nb'
    >>> decode_output('tab\\011x')
    'tab\tx'

    An escaped backslash collapses to one, and plain text is untouched:

    >>> decode_output('a\\134b')
    'a\\b'
    >>> decode_output('plain text, spaces kept')
    'plain text, spaces kept'

    A lone trailing backslash passes through:

    >>> decode_output('trailing\\')
    'trailing\\'
    """
    return unescape_control_output(payload).decode(errors="replace")


def output_payload(
    notification: ControlNotification,
    pane_id: str,
) -> str | None:
    r"""Return an output notification's decoded text for *pane_id*.

    Pane bytes are decoded once by :meth:`ControlNotification.parse`; this
    filter selects the requested pane and performs only the application-level
    bytes-to-text conversion.

    Parameters
    ----------
    notification : ControlNotification
        A typed control-mode notification.
    pane_id : str
        The concrete pane id (``%N``) to match.

    Returns
    -------
    str or None
        The decoded payload, or ``None`` when *raw* is not an ``%output`` frame
        for *pane_id*.

    Examples
    --------
    Internal whitespace is preserved exactly:

    >>> from libtmux.experimental.engines import ControlNotification
    >>> notification = ControlNotification.parse(b'%output %1 a  b')
    >>> output_payload(notification, '%1')
    'a  b'

    A frame for another pane, or a non-output frame, is ignored:

    >>> output_payload(ControlNotification.parse(b'%output %2 x'), '%1') is None
    True
    >>> output_payload(ControlNotification.parse(b'%window-add @3'), '%1') is None
    True
    """
    if notification.pane_id != pane_id or notification.payload is None:
        return None
    return notification.payload.decode(errors="replace")


async def accumulate_until_settle(
    frames: AsyncGenerator[str, None],
    *,
    settle_ms: int,
    timeout_ms: int,
    max_bytes: int,
    now: Callable[[], float] = time.monotonic,
) -> SettleOutcome:
    r"""Fold a stream of decoded chunks until the pane settles.

    Resets an idle window on each chunk and returns ``reason='settled'`` when no
    chunk arrives for ``settle_ms``; ``'byte_cap'`` at ``max_bytes`` (tail
    preserved); ``'time_cap'`` when the overall ``timeout_ms`` budget is spent;
    ``'stream_end'`` when *frames* is exhausted. The wall-clock budget reads
    *now* (inject a scripted clock for deterministic ``time_cap`` tests); the idle
    window uses a real :func:`asyncio.wait_for`, so a fake stream that simply
    suspends settles deterministically with no scripted sleeps. The stream is
    closed via :func:`contextlib.aclosing` on every exit, including cancellation.

    Parameters
    ----------
    frames : AsyncGenerator[str, None]
        The decoded per-pane output chunks.
    settle_ms : int
        Idle gap that counts as "settled".
    timeout_ms : int
        Overall wall-clock budget.
    max_bytes : int
        Byte cap; the returned text keeps the tail.
    now : Callable[[], float]
        Monotonic clock source, injectable for tests.

    Returns
    -------
    SettleOutcome
        The folded text plus the stop reason and counters.

    Examples
    --------
    A pane that emits two chunks then goes quiet settles on the idle window:

    >>> import asyncio
    >>> async def quiet_after_two():
    ...     yield "hello "
    ...     yield "world"
    ...     await asyncio.Event().wait()  # never another chunk -> idle fires
    >>> out = asyncio.run(
    ...     accumulate_until_settle(
    ...         quiet_after_two(), settle_ms=10, timeout_ms=1000, max_bytes=4096
    ...     )
    ... )
    >>> out.text, out.reason, out.byte_count
    ('hello world', 'settled', 11)

    A flood past the byte cap truncates (tail-preserving) and stops:

    >>> async def flood():
    ...     for _ in range(100):
    ...         yield "abcde"
    >>> out = asyncio.run(
    ...     accumulate_until_settle(
    ...         flood(), settle_ms=50, timeout_ms=1000, max_bytes=8
    ...     )
    ... )
    >>> out.reason, out.byte_count, out.truncated
    ('byte_cap', 8, True)

    An exhausted stream ends cleanly:

    >>> async def two_then_done():
    ...     yield "a"
    ...     yield "b"
    >>> asyncio.run(
    ...     accumulate_until_settle(
    ...         two_then_done(), settle_ms=50, timeout_ms=1000, max_bytes=64
    ...     )
    ... ).reason
    'stream_end'
    """
    buf: list[str] = []
    byte_count = frame_count = 0
    idle_ms_observed = 0
    reason: SettleReason = "stream_end"
    settle_s = settle_ms / 1000.0
    deadline = now() + timeout_ms / 1000.0
    async with contextlib.aclosing(frames):
        while True:
            remaining = deadline - now()
            if remaining <= 0:
                reason = "time_cap"
                break
            wait_s = min(settle_s, remaining)
            start = now()
            try:
                chunk = await asyncio.wait_for(frames.__anext__(), timeout=wait_s)
            except asyncio.TimeoutError:
                if now() - deadline >= 0:  # the wall-clock cap, not the idle gap
                    reason = "time_cap"
                else:  # idle window elapsed -> the pane went quiet
                    idle_ms_observed = int(settle_s * 1000)
                    reason = "settled"
                break
            except StopAsyncIteration:
                reason = "stream_end"
                break
            idle_ms_observed = int((now() - start) * 1000)
            buf.append(chunk)
            frame_count += 1
            byte_count += len(chunk.encode())
            if byte_count >= max_bytes:
                reason = "byte_cap"
                break
    text = "".join(buf)
    truncated = reason == "byte_cap"
    if truncated:  # keep the tail -- "did it finish" lives at the end
        text = text.encode()[-max_bytes:].decode(errors="replace")
    return SettleOutcome(
        text=text,
        reason=reason,
        byte_count=min(byte_count, max_bytes),
        frame_count=frame_count,
        idle_ms_observed=idle_ms_observed,
        truncated=truncated,
    )
