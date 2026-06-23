"""Live tmux event stream over MCP -- two interchangeable mechanisms (A/B).

A control-mode engine exposes tmux's asynchronous notifications (``%output``,
``%window-add``, ``%session-changed``, ...) as an ``async for`` stream via
``subscribe()``. FastMCP 3.x has no resource-subscription handshake and buffers a
tool's async generator into one list, so a live stream must be surfaced as
either:

- **push** -- a long-running ``watch_events`` tool that holds a ``Context`` and
  pushes each event as an MCP notification (real-time; best over streamable-http).
- **pull** -- a ``tmux://events`` resource backed by a ring buffer a background
  task fills, plus a ``poll_events`` tool; clients poll (stdio-friendly).

Which is registered is chosen by :func:`register_events` (driven by the
``LIBTMUX_MCP_EVENTS`` env var at the entrypoint). Both consume the engine's
single notification queue, so run one *or* the other per process when comparing.

The ``source`` axis selects the substrate: ``"output"`` streams raw
notifications; ``"subscription"`` first installs ``refresh-client -B`` format
subscriptions, tmux's debounced, server-side change detection.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import typing as t

from fastmcp import Context

from libtmux.experimental.engines.base import CommandRequest

if t.TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from fastmcp import FastMCP

    from libtmux.experimental.engines.base import AsyncTmuxEngine, CommandResult

EventMode = t.Literal["off", "push", "pull", "both"]
EventSource = t.Literal["subscription", "output"]

_RING_SIZE = 1024


class _StreamEngine(t.Protocol):
    """An async engine that also exposes a ``subscribe()`` notification stream.

    The general :class:`~..engines.base.AsyncTmuxEngine` protocol does not declare
    ``subscribe`` (only the control-mode engine has it), so the event tools type
    against this narrower protocol after the :func:`_supports_stream` guard.
    """

    async def run(self, request: CommandRequest) -> CommandResult:
        """Execute one tmux command."""
        ...

    async def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Execute a batch of tmux commands."""
        ...

    def subscribe(self) -> AsyncIterator[t.Any]:
        """Yield tmux notifications as they arrive."""
        ...


def _supports_stream(engine: AsyncTmuxEngine) -> bool:
    """Whether *engine* exposes a ``subscribe()`` notification stream."""
    return callable(getattr(engine, "subscribe", None))


def _event_dict(notification: t.Any) -> dict[str, t.Any]:
    """Project a ``ControlNotification`` to a JSON-friendly dict."""
    return {
        "kind": notification.kind,
        "args": list(notification.args),
        "raw": notification.raw,
    }


async def _install_subscriptions(
    engine: _StreamEngine,
    specs: list[str] | None,
) -> None:
    """Install ``refresh-client -B`` format subscriptions (``name:what:format``)."""
    for spec in specs or []:
        await engine.run(CommandRequest.from_args("refresh-client", "-B", spec))


class _EventRing:
    """A bounded ring buffer fed by a single background ``subscribe()`` reader.

    Each event gets a monotonic sequence number so a ``poll_events`` caller can
    ask for "everything since N" without re-reading the whole buffer.
    """

    def __init__(self, engine: _StreamEngine, maxlen: int = _RING_SIZE) -> None:
        self._engine = engine
        self._buffer: collections.deque[tuple[int, dict[str, t.Any]]] = (
            collections.deque(maxlen=maxlen)
        )
        self._seq = 0
        self._task: asyncio.Task[None] | None = None

    def _ensure_started(self) -> None:
        """Start the drainer task once, lazily, on the running loop."""
        if self._task is None:
            self._task = asyncio.create_task(self._drain(), name="libtmux-mcp-events")

    async def _drain(self) -> None:
        """Copy every notification into the ring buffer."""
        stream: AsyncIterator[t.Any] = self._engine.subscribe()
        async for notification in stream:
            self._seq += 1
            self._buffer.append((self._seq, _event_dict(notification)))

    def since(self, seq: int) -> dict[str, t.Any]:
        """Return buffered events with sequence number greater than *seq*."""
        self._ensure_started()
        events = [event for n, event in self._buffer if n > seq]
        return {"events": events, "cursor": self._seq}


def register_events(
    mcp: FastMCP,
    engine: AsyncTmuxEngine,
    *,
    mode: EventMode = "push",
    source: EventSource = "subscription",
) -> None:
    """Register the event stream tools/resource on *mcp* per *mode*.

    Does nothing when *mode* is ``"off"`` or *engine* has no ``subscribe()``
    stream (e.g. a subprocess engine) -- the live stream is a control-mode
    feature.
    """
    if mode == "off" or not _supports_stream(engine):
        return
    stream = t.cast("_StreamEngine", engine)
    if mode in ("push", "both"):
        _register_push(mcp, stream, source=source)
    if mode in ("pull", "both"):
        _register_pull(mcp, stream)


def _register_push(
    mcp: FastMCP,
    engine: _StreamEngine,
    *,
    source: EventSource,
) -> None:
    """Register the long-running ``watch_events`` push tool."""
    from fastmcp.tools import FunctionTool
    from mcp.types import ToolAnnotations

    async def watch_events(
        ctx: Context,
        kinds: list[str] | None = None,
        max_events: int = 20,
        timeout: float = 30.0,
        subscriptions: list[str] | None = None,
    ) -> dict[str, t.Any]:
        """Stream live tmux notifications, pushing each as an MCP log message.

        Returns after *max_events* notifications or *timeout* seconds, whichever
        comes first. ``kinds`` filters by notification kind (e.g. ``window-add``,
        ``output``). With ``source="subscription"``, pass ``subscriptions`` as
        ``name:what:format`` specs to install ``refresh-client -B`` watches first.
        """
        if source == "subscription":
            await _install_subscriptions(engine, subscriptions)
        collected: list[dict[str, t.Any]] = []

        async def _collect() -> None:
            async for notification in engine.subscribe():
                if kinds and notification.kind not in kinds:
                    continue
                await ctx.info(notification.raw)
                collected.append(_event_dict(notification))
                if max_events and len(collected) >= max_events:
                    return

        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(_collect(), timeout=timeout)
        return {"events": collected, "count": len(collected)}

    tool = FunctionTool.from_function(
        watch_events,
        name="watch_events",
        description="Stream live tmux notifications as MCP messages",
        tags={"readonly", "events"},
        annotations=ToolAnnotations(title="watch_events", readOnlyHint=True),
    )
    mcp.add_tool(tool)


def _register_pull(mcp: FastMCP, engine: _StreamEngine) -> None:
    """Register the ``tmux://events`` resource + ``poll_events`` pull tool."""
    from fastmcp.tools import FunctionTool
    from mcp.types import ToolAnnotations

    ring = _EventRing(engine)

    async def read_events() -> dict[str, t.Any]:
        """Return all buffered tmux events (starts the reader on first read)."""
        return ring.since(0)

    mcp.resource(
        "tmux://events",
        name="tmux-events",
        description="Buffered tmux control-mode notifications",
    )(read_events)

    async def poll_events(since: int = 0) -> dict[str, t.Any]:
        """Return tmux events with sequence number greater than *since*.

        The response ``cursor`` is the latest sequence number; pass it back as
        ``since`` next call to receive only newer events.
        """
        return ring.since(since)

    tool = FunctionTool.from_function(
        poll_events,
        name="poll_events",
        description="Poll buffered tmux events since a cursor",
        tags={"readonly", "events"},
        annotations=ToolAnnotations(title="poll_events", readOnlyHint=True),
    )
    mcp.add_tool(tool)
