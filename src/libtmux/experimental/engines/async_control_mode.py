"""An asynchronous control-mode (``tmux -C``) engine with an event stream.

A real async control engine -- not an ``asyncio.to_thread`` wrapper around the
sync one. It holds a persistent ``tmux -C`` connection, reads it from a single
background task, correlates each command to an :class:`asyncio.Future`, and
exposes tmux's asynchronous notifications (``%output``, ``%window-add``, ...) as
an ``async for`` event stream.

Design, informed by prior libtmux/mux control-mode work:

- The I/O-free :class:`~.control_mode.ControlModeParser` is reused verbatim; only
  the I/O layer differs from the sync engine (``await stdout.read`` instead of
  ``selectors``).
- Command correlation is a FIFO of futures resolved in block-arrival order. A
  block that arrives with *no* pending command is **unsolicited** (a hook-
  triggered command, or the startup ACK) and is skipped, so correlation never
  desyncs. The startup ACK is consumed synchronously in :meth:`start` before the
  reader launches, closing the startup race.
- A reader failure or EOF marks the engine *dead* and fails every pending
  command, rather than hanging.
- Notifications go to a bounded queue; on overflow the oldest is dropped and
  counted (backpressure), mirroring control mode's own ``%pause`` philosophy.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import shutil
import typing as t
from dataclasses import dataclass, field

from libtmux import exc
from libtmux.experimental.engines.base import render_control_line
from libtmux.experimental.engines.control_mode import (
    ControlModeError,
    ControlModeParser,
    _merge_blocks,
    command_count,
)

if t.TYPE_CHECKING:
    import types
    from collections.abc import AsyncIterator, Sequence

    from libtmux.experimental.engines.base import CommandRequest, CommandResult
    from libtmux.experimental.engines.control_mode import ControlModeBlock

_READ_CHUNK = 65536
_DEFAULT_TIMEOUT = 30.0
_STARTUP_TIMEOUT = 5.0
_STOP_TIMEOUT = 2.0

_STREAM_END = object()  # broadcast to subscriber queues to end their async for


@dataclass(frozen=True)
class ControlNotification:
    """An asynchronous tmux control-mode notification.

    Examples
    --------
    >>> ControlNotification.parse(b"%window-add @3")
    ControlNotification(kind='window-add', args=('@3',), raw='%window-add @3')
    >>> ControlNotification.parse(b"%output %1 hello world").kind
    'output'
    """

    kind: str
    args: tuple[str, ...]
    raw: str

    @classmethod
    def parse(cls, line: bytes) -> ControlNotification:
        """Parse a raw ``%``-notification line."""
        text = line.decode(errors="replace")
        body = text[1:] if text.startswith("%") else text
        parts = body.split(" ")
        kind = parts[0] if parts else ""
        return cls(kind=kind, args=tuple(parts[1:]), raw=text)


@dataclass(slots=True)
class _PendingCommand:
    future: asyncio.Future[CommandResult]
    argv: tuple[str, ...]
    expected: int
    blocks: list[ControlModeBlock] = field(default_factory=list)


def _offer(
    queue: asyncio.Queue[ControlNotification],
    notification: ControlNotification,
) -> int:
    """Put *notification* on *queue*, dropping the oldest on overflow.

    Returns ``1`` when a notification was dropped, else ``0`` (so a broadcast can
    tally drops without a ``try``/``except`` in its hot loop).
    """
    try:
        queue.put_nowait(notification)
    except asyncio.QueueFull:
        with contextlib.suppress(asyncio.QueueEmpty):
            queue.get_nowait()
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(notification)
        return 1
    return 0


def _force_put(queue: asyncio.Queue[t.Any], item: t.Any) -> None:
    """Put *item* on *queue*, evicting the oldest entry first when it is full.

    Like :func:`_offer` but drop-count-free: used to land the stream-end
    sentinel even on a queue already at ``maxsize``, so a slow consumer that hit
    backpressure still gets closed instead of hanging on ``queue.get()``. Pulled
    out of the broadcast loop so the ``try``/``except`` stays out of it.
    """
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        with contextlib.suppress(asyncio.QueueEmpty):
            queue.get_nowait()  # evict oldest; tolerable at death
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(item)


class AsyncControlModeEngine:
    """Execute tmux commands over one persistent async ``tmux -C`` connection.

    Parameters
    ----------
    tmux_bin : str or None
        The tmux binary; resolved via :func:`shutil.which` when ``None``.
    server_args : Sequence[str]
        Connection flags inserted before ``-C``.
    timeout : float
        Seconds to await a command's result before failing it.
    event_queue_size : int
        Bounded size of the notification queue (backpressure).

    Notes
    -----
    The connection opens lazily on first use. Use the engine as an async context
    manager, or call :meth:`aclose`, to tear it down.
    """

    def __init__(
        self,
        tmux_bin: str | None = None,
        *,
        server_args: Sequence[str] = (),
        timeout: float = _DEFAULT_TIMEOUT,
        event_queue_size: int = 4096,
    ) -> None:
        self.tmux_bin = tmux_bin
        self.server_args = tuple(server_args)
        self.timeout = timeout
        self._parser = ControlModeParser()
        self._pending: collections.deque[_PendingCommand] = collections.deque()
        self._event_queue_size = event_queue_size
        self._subscribers: set[asyncio.Queue[t.Any]] = set()
        self._dropped_notifications = 0
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._start_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._started = False
        self._dead: BaseException | None = None

    async def start(self) -> None:
        """Spawn ``tmux -C``, consume the startup ACK, and start the reader."""
        async with self._start_lock:
            if self._started:
                return
            tmux_bin = self.tmux_bin or shutil.which("tmux")
            if tmux_bin is None:
                raise exc.TmuxCommandNotFound
            cmd = [tmux_bin, *self.server_args, "-C"]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError:
                raise exc.TmuxCommandNotFound from None
            self._proc = proc
            self._dead = None
            await self._consume_startup()
            self._reader_task = asyncio.create_task(
                self._reader(),
                name="libtmux-async-control-reader",
            )
            self._started = True

    async def _consume_startup(self) -> None:
        """Read and discard tmux's startup ACK block before commands flow.

        Doing this synchronously (before the reader task launches and before any
        command future is queued) means the startup block can never be matched
        to a real command.
        """
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _STARTUP_TIMEOUT
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return
            try:
                chunk = await asyncio.wait_for(
                    proc.stdout.read(_READ_CHUNK),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                return
            if not chunk:
                return
            self._parser.feed(chunk)
            self._parser.notifications()  # discard any startup notifications
            if self._parser.blocks():  # startup ACK seen and discarded
                return

    async def run(self, request: CommandRequest) -> CommandResult:
        """Execute one tmux command over the control connection."""
        return (await self.run_batch([request]))[0]

    async def run_batch(
        self, requests: Sequence[CommandRequest]
    ) -> list[CommandResult]:
        """Pipeline a batch of commands; one result per request, in order."""
        if not requests:
            return []
        await self.start()
        if self._dead is not None:
            msg = "control-mode engine is dead"
            raise ControlModeError(msg) from self._dead

        loop = asyncio.get_running_loop()
        rendered = [tuple(req.args) for req in requests]
        futures: list[asyncio.Future[CommandResult]] = []
        async with self._write_lock:
            proc = self._proc
            if proc is None or proc.stdin is None:
                msg = "control-mode subprocess is not connected"
                raise ControlModeError(msg)
            appended: list[_PendingCommand] = []
            for argv in rendered:
                future: asyncio.Future[CommandResult] = loop.create_future()
                pending = _PendingCommand(future, argv, command_count(argv))
                self._pending.append(pending)
                appended.append(pending)
                futures.append(future)
            payload = b"".join(
                (render_control_line(argv) + "\n").encode() for argv in rendered
            )
            try:
                proc.stdin.write(payload)
                await proc.stdin.drain()
            except (BrokenPipeError, OSError) as error:
                # Remove the futures we just queued so a write failure cannot
                # leave orphans that desync FIFO correlation for the next batch.
                cm_error = ControlModeError(f"tmux control-mode write failed: {error}")
                for queued in appended:
                    with contextlib.suppress(ValueError):
                        self._pending.remove(queued)
                    if not queued.future.done():
                        queued.future.set_exception(cm_error)
                raise cm_error from error

        try:
            return await asyncio.wait_for(
                asyncio.gather(*futures),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError as error:
            # The futures stay queued (now cancelled); the reader drains their
            # blocks on arrival, keeping FIFO correlation aligned.
            msg = f"tmux control-mode timed out after {self.timeout}s"
            raise ControlModeError(msg) from error

    async def subscribe(self) -> AsyncIterator[ControlNotification]:
        """Yield asynchronous tmux notifications as they arrive.

        Each subscriber gets its own queue, so concurrent subscribers (the event
        push tool, the pull ring, the output monitor) each see *every*
        notification rather than competing for one shared stream. The iterator
        runs until the engine is closed or the caller stops iterating; its queue
        is unregistered on exit. When the engine dies, ``_STREAM_END`` is
        broadcast to every subscriber queue so the ``async for`` ends cleanly
        instead of hanging on ``queue.get()``.
        """
        queue: asyncio.Queue[t.Any] = asyncio.Queue(
            maxsize=self._event_queue_size,
        )
        self._subscribers.add(queue)
        try:
            while True:
                item = await queue.get()
                if item is _STREAM_END:
                    return
                yield item
        finally:
            self._subscribers.discard(queue)

    @property
    def dropped_notifications(self) -> int:
        """How many notifications were dropped due to a full event queue."""
        return self._dropped_notifications

    async def aclose(self) -> None:
        """Tear down the connection: cancel the reader, fail pending, kill proc."""
        if not self._started:
            return
        self._started = False
        reader = self._reader_task
        self._reader_task = None
        if reader is not None:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader
        self._broadcast_stream_end()
        self._fail_pending(ControlModeError("control-mode engine closed"))
        proc = self._proc
        self._proc = None
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=_STOP_TIMEOUT)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()

    async def __aenter__(self) -> AsyncControlModeEngine:
        """Start the engine on context entry."""
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Close the engine on context exit."""
        await self.aclose()

    async def _reader(self) -> None:
        """Background task: read tmux output, resolve futures, publish events."""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        stdout = proc.stdout
        try:
            while True:
                chunk = await stdout.read(_READ_CHUNK)
                if not chunk:
                    self._mark_dead(ControlModeError("tmux -C closed stdout"))
                    return
                self._parser.feed(chunk)
                for block in self._parser.blocks():
                    self._dispatch_block(block)
                for line in self._parser.notifications():
                    self._publish(line)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._mark_dead(ControlModeError(f"control-mode reader failed: {error}"))

    def _dispatch_block(self, block: ControlModeBlock) -> None:
        """Accumulate a solicited block; resolve the command once it has them all.

        A ``;``-folded command emits one block per sub-command; unsolicited blocks
        (hook-triggered commands, the startup ACK) carry flags 0 and are skipped,
        so FIFO correlation never desyncs.
        """
        if block.flags != 1:
            return  # unsolicited (hook-triggered command or startup ACK): skip
        if not self._pending:
            return
        pending = self._pending[0]
        pending.blocks.append(block)
        if len(pending.blocks) < pending.expected:
            return
        self._pending.popleft()
        if not pending.future.done():
            pending.future.set_result(_merge_blocks(pending.blocks, pending.argv))

    def _publish(self, line: bytes) -> None:
        """Broadcast a notification to every subscriber (drop-oldest per queue).

        Runs synchronously from the single reader task, so the subscriber set is
        never mutated mid-iteration.
        """
        notification = ControlNotification.parse(line)
        for queue in self._subscribers:
            self._dropped_notifications += _offer(queue, notification)

    def _broadcast_stream_end(self) -> None:
        """Push the stream-end sentinel to every subscriber, then clear them.

        Uses :func:`_force_put` so the sentinel lands even on a queue already at
        ``maxsize`` (a slow consumer that hit backpressure); otherwise the
        sentinel would be lost and the consumer would hang forever on
        ``queue.get()`` -- the exact bug this guards against.
        """
        for queue in list(self._subscribers):
            _force_put(queue, _STREAM_END)
        self._subscribers.clear()

    def _mark_dead(self, error: BaseException) -> None:
        """Record the engine as dead and fail all pending commands."""
        if self._dead is None:
            self._dead = error
        self._fail_pending(error)
        self._broadcast_stream_end()

    def _fail_pending(self, error: BaseException) -> None:
        """Fail every queued command future with *error*."""
        while self._pending:
            pending = self._pending.popleft()
            if not pending.future.done():
                pending.future.set_exception(error)

    @classmethod
    def for_server(cls, server: t.Any, **kwargs: t.Any) -> AsyncControlModeEngine:
        """Build an async control-mode engine bound to a live server's socket."""
        server_args: list[str] = []
        if getattr(server, "socket_name", None):
            server_args.append(f"-L{server.socket_name}")
        if getattr(server, "socket_path", None):
            server_args.append(f"-S{server.socket_path}")
        if getattr(server, "config_file", None):
            server_args.append(f"-f{server.config_file}")
        colors = getattr(server, "colors", None)
        if colors == 256:
            server_args.append("-2")
        elif colors == 88:
            server_args.append("-8")
        return cls(
            tmux_bin=getattr(server, "tmux_bin", None),
            server_args=server_args,
            **kwargs,
        )
