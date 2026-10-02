"""Stream one pane's output as an async iterator of bytes and gaps.

``async for item in stream`` yields ``bytes`` (a chunk of what the pane
printed, in order) and :class:`Gap` (output was discarded here). There is no
callback API and no public queue: one iterator per pane, and the consumer's
pace is the only thing that decides how much is buffered.

The stream never lets a slow consumer stall the pane. Its queue is bounded by
two watermarks. At ``high`` queued bytes the pane is paused at tmux; once the
consumer has drained to ``low`` it is resumed; tmux discards what the pane
prints while it is paused, and the stream says so with a :class:`Gap` at that
point in the sequence. Silent loss is the failure to rule out, so the stream
offers no policy that drops without a gap. ``policy="unbounded"`` never pauses
and never loses, and buffers whatever the consumer has not read; ask for it by
name.

Only a control-mode engine can stream, because only a control client receives
pane output.
"""

from __future__ import annotations

import typing as t

from libtmux import exc
from libtmux.engines.control.flow import Gap

if t.TYPE_CHECKING:
    import types

    from typing_extensions import Self

    from libtmux.engines.base import AsyncTmuxEngine
    from libtmux.engines.control.aio import OutputChannel

__all__ = ("Gap", "PaneStream")

_UNBOUNDED = 1 << 62


class PaneStream:
    """A pane's output, as an async context manager and async iterator.

    Parameters
    ----------
    engine : AsyncControlModeEngine
        The engine whose control client receives the pane's output.
    pane_id : str
        Pane id such as ``%3``. The pane must be in the session the control
        client is attached to.
    high, low : int
        Queued bytes at which the pane is paused, and resumed.
    policy : {"watermark", "unbounded"}
        ``"watermark"`` bounds the queue and reports loss as a :class:`Gap`.
        ``"unbounded"`` never pauses.

    Raises
    ------
    ~libtmux.exc.EngineError
        *engine* cannot stream.
    ValueError
        *pane_id* already has a stream, or the watermarks are not ``0 <= low <
        high``.

    Examples
    --------
    >>> import asyncio
    >>> from libtmux.aio.stream import Gap, PaneStream
    >>> from libtmux.engines import AsyncControlModeEngine, CommandRequest
    >>> async def demo():
    ...     async with AsyncControlModeEngine.for_server(server) as engine:
    ...         await engine.run(
    ...             CommandRequest.from_args("display-message", "-p", "up")
    ...         )
    ...         async with PaneStream(engine, pane.pane_id) as out:
    ...             await engine.run(
    ...                 CommandRequest.from_args(
    ...                     "send-keys",
    ...                     "-t",
    ...                     pane.pane_id,
    ...                     "printf '%s%s' str eam",
    ...                     "Enter",
    ...                 )
    ...             )
    ...             seen = b""
    ...             async for item in out:
    ...                 if not isinstance(item, Gap):
    ...                     seen += item
    ...                 if b"stream" in seen.replace(b"str eam", b""):
    ...                     return True
    >>> asyncio.run(demo())
    True
    """

    def __init__(
        self,
        engine: AsyncTmuxEngine,
        pane_id: str,
        *,
        high: int = 262_144,
        low: int = 65_536,
        policy: t.Literal["watermark", "unbounded"] = "watermark",
    ) -> None:
        if policy not in ("watermark", "unbounded"):
            msg = f"policy must be 'watermark' or 'unbounded', got {policy!r}"
            raise ValueError(msg)
        output = getattr(engine, "output", None)
        if output is None:
            msg = (
                f"{type(engine).__name__} cannot stream pane output; "
                "use AsyncControlModeEngine"
            )
            raise exc.EngineError(msg)
        self.pane_id = pane_id
        self._channel: OutputChannel = output(
            pane_id,
            high=_UNBOUNDED if policy == "unbounded" else high,
            low=0 if policy == "unbounded" else low,
        )

    @property
    def peak(self) -> int:
        """The most bytes ever queued at once."""
        return self._channel.peak

    @property
    def gaps(self) -> int:
        """How many gaps the stream has reported so far."""
        return self._channel.gaps

    def __aiter__(self) -> Self:
        """Return this stream."""
        return self

    async def __anext__(self) -> bytes | Gap:
        """Wait for the next chunk of output or the next gap."""
        return await self._channel.__anext__()

    async def aclose(self) -> None:
        """Stop streaming. What is already queued can still be read."""
        self._channel.close()

    async def __aenter__(self) -> Self:
        """Return this stream."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Stop streaming."""
        await self.aclose()
