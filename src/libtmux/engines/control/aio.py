"""An asyncio control-mode engine: one persistent ``tmux -C`` client, supervised.

:class:`AsyncControlModeEngine` is the asyncio twin of
:class:`~libtmux.engines.control.sync.ControlModeEngine`. It keeps one
``tmux -C attach-session`` client open on the event loop, writes commands as
quoted lines and matches the replies to callers in order. Because a reader task
owns the connection, it can also do what a blocking driver cannot:

- deliver tmux's notifications to any number of subscribers
  (:meth:`~AsyncControlModeEngine.notifications`),
- stream a pane's output with a bounded queue and an in-band
  :class:`~libtmux.engines.control.flow.Gap`
  (:meth:`~AsyncControlModeEngine.output`),
- wake a waiter when a pane prints (:meth:`~AsyncControlModeEngine.watch_output`),
- reconnect when the client dies and tell its subscribers.

The reader never stops reading. A consumer that falls behind is handled by
pausing the pane at tmux (``refresh-client -A %p:pause``), never by letting the
pipe fill, because a full pipe stalls the pane's own process.

Cancelling a caller is safe: its reply is still read and dropped when it
arrives, so the order of replies against requests cannot slip.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import logging
import shlex
import time
import typing as t
from dataclasses import dataclass

from libtmux import exc
from libtmux.engines.base import CommandRequest, CommandResult, command_count
from libtmux.engines.connection import ServerConnection
from libtmux.engines.control import protocol
from libtmux.engines.control.flow import Action, Gap, Watermark
from libtmux.engines.control.routing import blocks_queue
from libtmux.engines.exec import AsyncExecEngine
from libtmux.engines.subprocess import (
    AsyncSubprocessEngine,
    _kill_and_reap_async,
    spawn_async,
)

if t.TYPE_CHECKING:
    import types
    from collections.abc import Sequence

    from typing_extensions import Self

logger = logging.getLogger(__name__)

_READ_CHUNK = 65536
_STARTUP_TIMEOUT = 5.0
_DETACH_TIMEOUT = 2.0
_STDERR_LINES = 20
_STDERR_BYTES = 16384
_OFF_VALUES = frozenset({"off", "0"})
_BACKOFF_BASE = 0.1
_BACKOFF_CAP = 5.0
_STABLE_AFTER = 1.0
RECONNECTED = "libtmux-reconnected"
"""Name of the notification that marks a reconnect.

It is not a tmux notification: tmux names never start with ``libtmux-``. Its
``args`` are the new connection generation.
"""


@dataclass(frozen=True)
class Lagged:
    """A subscriber fell behind and notifications were dropped.

    It sits in the stream exactly where the loss happened.

    Attributes
    ----------
    count : int
        How many notifications were dropped at this point.

    Examples
    --------
    >>> Lagged(3)
    Lagged(count=3)
    """

    count: int


class _Slot:
    """One request's place in the reply order.

    The slot, not the caller, owns the reply: a caller that is cancelled or
    times out leaves the slot in the queue, and the reader still resolves it.
    The future only ever holds a value, never an exception, so an abandoned
    slot leaves nothing unretrieved.
    """

    __slots__ = ("blocks", "callback", "expected", "future")

    def __init__(
        self,
        expected: int,
        loop: asyncio.AbstractEventLoop,
        callback: t.Callable[[list[protocol.Block]], None] | None = None,
    ) -> None:
        self.expected = expected
        self.blocks: list[protocol.Block] = []
        self.callback = callback
        self.future: asyncio.Future[list[protocol.Block] | Exception] = (
            loop.create_future()
        )

    def finish(self, outcome: list[protocol.Block] | Exception) -> None:
        if not self.future.done():
            self.future.set_result(outcome)
        if self.callback is not None and not isinstance(outcome, Exception):
            self.callback(outcome)


class _Link:
    """One live ``tmux -C`` client and everything bound to it."""

    def __init__(self, process: asyncio.subprocess.Process, loop: t.Any) -> None:
        self.process = process
        self.parser = protocol.ControlModeParser()
        self.sequence = protocol.BlockSequenceMonitor()
        self.fifo: collections.deque[_Slot] = collections.deque()
        self.ack: asyncio.Future[protocol.Block | Exception] = loop.create_future()
        self.attached = False
        self.dead = asyncio.Event()
        self.closing = False
        self.reaped = False
        self.born = time.monotonic()
        self.stderr = bytearray()
        self.reader: asyncio.Future[None] | None = None
        self.stderr_reader: asyncio.Future[None] | None = None


class _Subscriber:
    """A bounded notification queue whose overflow is part of the stream."""

    def __init__(self, maxsize: int, owner: AsyncControlModeEngine) -> None:
        self.maxsize = maxsize
        self.items: collections.deque[protocol.Notification | Lagged] = (
            collections.deque()
        )
        self.wake = asyncio.Event()
        self.closed = False
        self.owner = owner

    def push(self, item: protocol.Notification) -> None:
        if self.closed:
            return
        if len(self.items) >= self.maxsize:
            last = self.items[-1] if self.items else None
            if isinstance(last, Lagged):
                self.items[-1] = Lagged(last.count + 1)
            else:
                self.items.append(Lagged(1))
        else:
            self.items.append(item)
        self.wake.set()

    def close(self) -> None:
        self.closed = True
        self.wake.set()


class NotificationStream:
    """An async iterator of tmux notifications, with overflow reported in order.

    Get one from :meth:`AsyncControlModeEngine.notifications`. Items are
    :class:`~libtmux.engines.control.protocol.Notification` (``name`` without
    the ``%``, ``args`` the rest of the line) and :class:`Lagged`. The iterator
    ends when the engine closes or the stream is closed.

    Examples
    --------
    >>> import asyncio
    >>> from libtmux.engines import CommandRequest
    >>> from libtmux.engines.control.aio import AsyncControlModeEngine
    >>> async def demo():
    ...     async with AsyncControlModeEngine.for_server(server) as engine:
    ...         with engine.notifications() as events:
    ...             await engine.run(
    ...                 CommandRequest.from_args(
    ...                     "rename-session", "-t", session.session_id, "renamed"
    ...                 )
    ...             )
    ...             async for event in events:
    ...                 if event.name == "session-renamed":
    ...                     return event.args
    >>> asyncio.run(demo())
    '$... renamed'
    """

    def __init__(self, subscriber: _Subscriber) -> None:
        self._subscriber = subscriber

    def __aiter__(self) -> Self:
        """Return this stream."""
        return self

    async def __anext__(self) -> protocol.Notification | Lagged:
        """Wait for the next notification or overflow marker."""
        sub = self._subscriber
        while True:
            if sub.items:
                return sub.items.popleft()
            if sub.closed:
                raise StopAsyncIteration
            sub.wake.clear()
            await sub.wake.wait()

    def close(self) -> None:
        """Stop receiving; the iterator ends once its queue is read."""
        self._subscriber.close()
        self._subscriber.owner._drop_subscriber(self._subscriber)

    def __enter__(self) -> Self:
        """Return this stream."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Close the stream."""
        self.close()


class OutputChannel:
    """One pane's output as an async iterator of ``bytes`` and ``Gap``.

    Get one from :meth:`AsyncControlModeEngine.output`. The queue is bounded by
    the watermarks: at ``high`` bytes the pane is paused at tmux, at ``low`` it
    is resumed, and a :class:`~libtmux.engines.control.flow.Gap` marks the
    output tmux discarded in between. The iterator ends when the channel or the
    engine closes. UTF-8 decoding is the consumer's job, because a character can
    straddle two chunks.
    """

    def __init__(
        self,
        engine: AsyncControlModeEngine,
        pane: str,
        *,
        high: int,
        low: int,
    ) -> None:
        self._engine = engine
        self.pane = pane
        self._buffer = Watermark(pane, high=high, low=low)
        self._wake = asyncio.Event()

    @property
    def peak(self) -> int:
        """The most bytes ever queued at once."""
        return self._buffer.peak

    @property
    def gaps(self) -> int:
        """How many gaps the stream has reported."""
        return self._buffer.gaps

    @property
    def queued(self) -> int:
        """Bytes waiting for the consumer."""
        return self._buffer.queued

    def __aiter__(self) -> Self:
        """Return this channel."""
        return self

    async def __anext__(self) -> bytes | Gap:
        """Wait for the next chunk or gap."""
        while True:
            item, action = self._buffer.pop()
            if action is not None:
                self._engine._flow(self, action)
            if item is not None:
                return item
            if self._buffer.closed:
                raise StopAsyncIteration
            self._wake.clear()
            await self._wake.wait()

    def close(self) -> None:
        """Stop the stream; queued items can still be read."""
        self._engine._drop_output(self)
        self._buffer.close()
        self._wake.set()

    # -- engine side ------------------------------------------------------

    def _feed(self, data: bytes) -> None:
        action = self._buffer.push(data)
        if action is not None:
            self._engine._flow(self, action)
        self._wake.set()

    def _pause_took_effect(self) -> None:
        action = self._buffer.pause_took_effect()
        if action is not None:
            self._engine._flow(self, action)
        self._wake.set()

    def _continue_took_effect(self) -> None:
        self._buffer.continue_took_effect()

    def _lost(self) -> None:
        self._buffer.lost()
        self._wake.set()

    def _end(self) -> None:
        self._buffer.close()
        self._wake.set()


class OutputWatch:
    """A wake-up for a pane's output, with no bytes kept.

    Get one from :meth:`AsyncControlModeEngine.watch_output`. :meth:`changed`
    returns when the pane has printed since it last returned, which is all a
    waiter needs: it then decides from the pane's rendered screen.
    """

    def __init__(self, engine: AsyncControlModeEngine, pane: str) -> None:
        self._engine = engine
        self.pane = pane
        self._wake = asyncio.Event()
        self._ended = False

    async def changed(self, timeout: float | None = None) -> bool:
        """Wait for output; return ``False`` when *timeout* elapses first.

        Returns ``True`` as well when the watch ended (the engine closed), so a
        waiter re-checks the pane instead of sleeping on a dead source.
        """
        if not self._wake.is_set():
            try:
                await asyncio.wait_for(self._wake.wait(), timeout)
            except asyncio.TimeoutError:
                return False
        self._wake.clear()
        return True

    def close(self) -> None:
        """Stop watching."""
        self._engine._drop_watch(self)
        self._end()

    def __enter__(self) -> Self:
        """Return this watch."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Stop watching."""
        self.close()

    def _feed(self) -> None:
        self._wake.set()

    def _end(self) -> None:
        self._ended = True
        self._wake.set()


class AsyncControlModeEngine:
    """Run tmux commands over one persistent control-mode client, on the loop.

    The client attaches to an existing session whose ``destroy-unattached``
    option is off (a bare ``tmux -C`` would create a throwaway session). While
    no such session exists, requests run in a subprocess. Commands that wait
    (``run-shell``, ``wait-for``, ``confirm-before``, a non-detached
    ``new-session``) and requests with ``input`` always run in a subprocess,
    because one waiting command would hold every command behind it.

    Parameters
    ----------
    tmux_bin : str, optional
        The tmux binary; resolved from ``$PATH`` when omitted.
    server_args : sequence of str
        Connection flags, such as ``("-Lwork",)``.
    prefix : sequence of str
        A transport command placed before tmux, such as
        ``("docker", "exec", "-i", "box")``: one persistent ``tmux -C`` through
        it replaces a handshake per command.
    shell : bool
        Quote tmux's argv into one word for a transport that re-parses it, such
        as ``ssh``. See :class:`~libtmux.engines.exec.ExecEngine`.
    pause_after : int, optional
        Seconds of lag after which *tmux* pauses the client's panes. Off by
        default: the engine paces panes itself, and tmux's own limit kills a
        client that lags five minutes.

    Notes
    -----
    A request that finds the client gone raises
    :exc:`~libtmux.exc.ControlConnectionLost`; the next request reconnects, and
    :attr:`generation` counts the connections. While anything subscribes
    (:meth:`notifications`, :meth:`output`, :meth:`watch_output`) a supervisor
    reconnects on its own, with a growing delay between failed attempts, tells
    each subscriber, and gives every output stream a
    :class:`~libtmux.engines.control.flow.Gap`.

    Cancelling a call never desynchronises the connection: tmux still sends the
    reply, and the reader drops it. The command may still run on the server.

    Examples
    --------
    >>> import asyncio
    >>> from libtmux.engines import CommandRequest
    >>> async def demo():
    ...     async with AsyncControlModeEngine.for_server(server) as engine:
    ...         result = await engine.run(
    ...             CommandRequest.from_args("display-message", "-p", "hi")
    ...         )
    ...         return result.stdout, engine.generation
    >>> asyncio.run(demo())
    (('hi',), 1)
    """

    def __init__(
        self,
        tmux_bin: str | None = None,
        *,
        server_args: Sequence[str] = (),
        prefix: Sequence[str] = (),
        shell: bool = False,
        pause_after: int | None = None,
    ) -> None:
        self._conn = ServerConnection.of(tmux_bin, server_args)
        self._prefix = tuple(prefix)
        self._shell = shell
        self._pause_after = pause_after
        self._fallback: AsyncSubprocessEngine | AsyncExecEngine = (
            AsyncExecEngine(
                self._prefix,
                tmux=self._conn.tmux_bin or "tmux",
                socket_args=self._conn.args,
                shell=shell,
            )
            if self._prefix
            else AsyncSubprocessEngine(self._conn)
        )
        self._closed = False
        self._generation = 0
        self._link: _Link | None = None
        self._connect_lock: asyncio.Lock | None = None
        self._subscribers: list[_Subscriber] = []
        self._outputs: dict[str, OutputChannel] = {}
        self._watches: dict[str, list[OutputWatch]] = {}
        self._supervisor: asyncio.Future[None] | None = None
        self._demand = asyncio.Event()
        self._background: set[asyncio.Future[t.Any]] = set()
        self._silenced = True

    @classmethod
    def for_server(cls, server: t.Any, **kwargs: t.Any) -> Self:
        """Build an engine bound to a live :class:`libtmux.Server`'s socket.

        Examples
        --------
        >>> AsyncControlModeEngine.for_server(server).server_args[0].startswith("-L")
        True
        """
        conn = ServerConnection.from_server(server)
        return cls(conn.tmux_bin, server_args=conn.args, **kwargs)

    def with_connection(self, connection: ServerConnection) -> Self:
        """Return an equivalent, unconnected engine bound to *connection*.

        Examples
        --------
        >>> from libtmux.engines import ServerConnection
        >>> AsyncControlModeEngine().with_connection(
        ...     ServerConnection.of(args=("-Lwork",))
        ... ).server_args
        ('-Lwork',)
        """
        return type(self)(
            connection.tmux_bin,
            server_args=connection.args,
            prefix=self._prefix,
            shell=self._shell,
            pause_after=self._pause_after,
        )

    @property
    def connection(self) -> ServerConnection:
        """The tmux binary and connection flags this engine dispatches over."""
        return self._conn

    @property
    def tmux_bin(self) -> str | None:
        """The explicitly configured tmux binary, if any."""
        return self._conn.tmux_bin

    @property
    def server_args(self) -> tuple[str, ...]:
        """Connection flags placed before ``-C``."""
        return self._conn.args

    @property
    def generation(self) -> int:
        """How many control connections this engine has opened.

        Examples
        --------
        >>> AsyncControlModeEngine().generation
        0
        """
        return self._generation

    @property
    def connected(self) -> bool:
        """Whether a control client is attached right now."""
        link = self._link
        return link is not None and link.attached and not link.dead.is_set()

    async def tmux_version(self) -> str | None:
        """Report the tmux version this engine targets (memoized)."""
        return await self._fallback.tmux_version()

    def command_line(self, request: CommandRequest) -> tuple[str, ...]:
        """Return the argv a subprocess would run for *request*.

        A control request has no argv of its own; this is the equivalent
        command line, which is what :attr:`CommandResult.cmd` reports.
        """
        return self._fallback.command_line(request)

    # -- public API ------------------------------------------------------

    async def run(self, request: CommandRequest) -> CommandResult:
        """Run one command and return its result.

        Raises
        ------
        ~libtmux.exc.EngineClosed
            The engine was closed.
        ~libtmux.exc.ControlConnectionLost
            The control client exited before replying.
        ~libtmux.exc.ControlProtocolError
            tmux's output was malformed; the connection is discarded.
        ~libtmux.exc.TmuxTimeout
            ``request.timeout`` elapsed; the reply is dropped when it arrives
            and the connection stays up.
        ~libtmux.exc.TmuxCommandNotFound
            The tmux binary is missing.
        asyncio.CancelledError
            The caller was cancelled; the reply is dropped when it arrives.
        """
        return (await self.run_batch([request]))[0]

    async def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Run requests in order, pipelining those that share the connection.

        Consecutive control-eligible requests are written together and their
        replies read back in order. A request that must run in a subprocess
        ends the pipeline, runs, and a new pipeline starts after it.
        """
        results: list[CommandResult] = []
        pipeline: list[CommandRequest] = []
        for request in requests:
            if blocks_queue(request.args) or request.input is not None:
                results += await self._run_pipeline(pipeline)
                pipeline = []
                self._raise_if_closed()
                results.append(await self._fallback.run(request))
            else:
                pipeline.append(request)
        results += await self._run_pipeline(pipeline)
        return results

    def notifications(self, *, maxsize: int = 1024) -> NotificationStream:
        """Subscribe to tmux's notifications.

        Every subscriber gets every notification from the moment this returns.
        A subscriber that falls more than *maxsize* behind loses the newest
        notifications and finds a :class:`Lagged` in the stream where they
        would have been. Pane output is not a notification; use
        :meth:`output` for that. After a reconnect the stream carries a
        notification named :data:`RECONNECTED`, so a subscriber knows events
        may have been missed.

        Parameters
        ----------
        maxsize : int
            Notifications a slow subscriber may have queued.

        Returns
        -------
        NotificationStream
            An async iterator that is also a context manager. After the engine
            closes it is already ended.
        """
        if maxsize < 1:
            msg = f"maxsize must be at least 1, got {maxsize}"
            raise ValueError(msg)
        subscriber = _Subscriber(maxsize, self)
        if self._closed:
            subscriber.close()
        else:
            self._subscribers.append(subscriber)
            self._want_connection()
        return NotificationStream(subscriber)

    def output(
        self,
        pane: str,
        *,
        high: int = 262_144,
        low: int = 65_536,
    ) -> OutputChannel:
        """Stream a pane's output, paused and resumed at the watermarks.

        Parameters
        ----------
        pane : str
            Pane id such as ``%3``. Only panes in the session the client is
            attached to produce output.
        high, low : int
            Queued bytes at which the pane is paused and resumed.

        Raises
        ------
        ValueError
            *pane* already has a stream.
        """
        if pane in self._outputs:
            msg = f"pane {pane} already has an output stream"
            raise ValueError(msg)
        channel = OutputChannel(self, pane, high=high, low=low)
        if self._closed:
            channel._end()
            return channel
        self._outputs[pane] = channel
        self._sinks_changed()
        return channel

    def watch_output(self, pane: str) -> OutputWatch:
        """Wake when *pane* prints, without keeping its bytes.

        Returns
        -------
        OutputWatch
            Call :meth:`OutputWatch.changed` to wait; close it when done.
        """
        watch = OutputWatch(self, pane)
        if self._closed:
            watch._end()
            return watch
        self._watches.setdefault(pane, []).append(watch)
        self._sinks_changed()
        return watch

    async def aclose(self) -> None:
        """Detach the control client and reap it. Safe to call twice.

        Pending calls fail with :exc:`~libtmux.exc.EngineClosed`, every
        notification, output and watch iterator ends, and the client is gone
        when this returns: stdin is closed so tmux detaches, and a client that
        has not exited within two seconds is killed and reaped.
        """
        if self._closed:
            return
        self._closed = True
        supervisor, self._supervisor = self._supervisor, None
        if supervisor is not None:
            supervisor.cancel()
            await asyncio.wait({supervisor})
            if not supervisor.cancelled():
                supervisor.exception()
        for subscriber in self._subscribers:
            subscriber.close()
        self._subscribers.clear()
        for channel in list(self._outputs.values()):
            channel._end()
        self._outputs.clear()
        for watches in list(self._watches.values()):
            for watch in watches:
                watch._end()
        self._watches.clear()
        link, self._link = self._link, None
        if link is not None:
            await self._teardown(
                link,
                exc.EngineClosed("the engine is closed"),
                graceful=True,
            )
        for task in list(self._background):
            task.cancel()
        if self._background:
            await asyncio.wait(self._background)
        await self._fallback.aclose()

    async def __aenter__(self) -> Self:
        """Return this engine."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Close the engine."""
        await self.aclose()

    # -- requests --------------------------------------------------------

    def _raise_if_closed(self) -> None:
        if self._closed:
            msg = "the control-mode engine is closed"
            raise exc.EngineClosed(msg)

    async def _run_pipeline(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        if not requests:
            return []
        # Encode everything first: an argument tmux cannot be sent must fail
        # before any reply slot exists for it.
        lines = [protocol.encode_command(request.args) for request in requests]
        self._raise_if_closed()
        link = await self._ensure_link()
        if link is None:
            return [await self._fallback.run(request) for request in requests]
        slots = self._submit(link, requests, b"".join(lines))
        await self._drain(link)
        return [
            await self._collect(link, request, slot)
            for request, slot in zip(requests, slots, strict=True)
        ]

    def _submit(
        self,
        link: _Link,
        requests: Sequence[CommandRequest],
        payload: bytes,
        callbacks: Sequence[t.Callable[[list[protocol.Block]], None] | None] = (),
    ) -> list[_Slot]:
        """Queue a reply slot per request and write *payload*, without yielding.

        Nothing awaits between queueing and writing, so the order of slots is
        the order of lines on the wire.
        """
        stdin = link.process.stdin
        if link.dead.is_set() or stdin is None or stdin.is_closing():
            raise self._lost(link)
        loop = asyncio.get_running_loop()
        slots = [
            _Slot(
                command_count(request.args),
                loop,
                callbacks[i] if i < len(callbacks) else None,
            )
            for i, request in enumerate(requests)
        ]
        link.fifo.extend(slots)
        stdin.write(payload)
        return slots

    async def _drain(self, link: _Link) -> None:
        stdin = link.process.stdin
        assert stdin is not None
        # The reader sees the client go and fails every slot, so a broken pipe
        # here needs no handling of its own.
        with contextlib.suppress(ConnectionError):
            await stdin.drain()

    async def _collect(
        self,
        link: _Link,
        request: CommandRequest,
        slot: _Slot,
    ) -> CommandResult:
        done, _ = await asyncio.wait({slot.future}, timeout=request.timeout)
        if not done:
            assert request.timeout is not None
            cmd = self.command_line(request)
            logger.error(
                "tmux control command timed out",
                extra={"tmux_cmd": shlex.join(cmd), "tmux_timeout": request.timeout},
            )
            raise exc.TmuxTimeout(cmd=list(cmd), timeout=request.timeout)
        outcome = slot.future.result()
        if isinstance(outcome, Exception):
            raise outcome
        return protocol.result_from_blocks(self.command_line(request), outcome)

    # -- connection ------------------------------------------------------

    async def _ensure_link(self) -> _Link | None:
        """Return the live link, opening one if needed; ``None`` with no session."""
        link = self._link
        if link is not None and not link.dead.is_set():
            return link
        if self._connect_lock is None:
            self._connect_lock = asyncio.Lock()
        async with self._connect_lock:
            link = self._link
            if link is not None and not link.dead.is_set():
                return link
            self._raise_if_closed()
            target = await self._find_attach_target()
            if target is None:
                return None
            return await self._start(target)

    async def _find_attach_target(self) -> str | None:
        """Return a session id whose ``destroy-unattached`` is already off.

        Reads only: nothing about any session's options is changed, so opening
        the connection cannot cause a session to be destroyed.
        """
        listing = await self._fallback.run(
            CommandRequest.from_args(
                "list-sessions",
                "-F",
                "#{session_id} #{destroy-unattached}",
            ),
        )
        if listing.returncode != 0:
            return None
        for row in listing.stdout:
            session_id, _, policy = row.partition(" ")
            if session_id and policy in _OFF_VALUES:
                return session_id
        return None

    def _argv(self, target: str) -> tuple[str, ...]:
        tmux_argv = self._conn.argv("-u", "-C", "attach-session", "-E", "-t", target)
        if self._prefix and self._conn.tmux_bin is None:
            tmux_argv = ("tmux", *tmux_argv[1:])
        if not self._prefix:
            return tmux_argv
        if self._shell:
            return (*self._prefix, shlex.join(tmux_argv))
        return (*self._prefix, *tmux_argv)

    async def _start(self, target: str) -> _Link:
        argv = self._argv(target)
        process = await spawn_async(argv, stdin=asyncio.subprocess.PIPE)
        loop = asyncio.get_running_loop()
        link = _Link(process, loop)
        link.reader = asyncio.ensure_future(self._read(link))
        link.stderr_reader = asyncio.ensure_future(self._read_stderr(link))
        try:
            await self._await_attach(link)
            self._link = link
            self._generation += 1
            await self._handshake(link)
        except BaseException as error:
            if self._link is link:
                self._link = None
            await self._teardown(
                link,
                error
                if isinstance(error, Exception)
                else exc.EngineClosed("cancelled"),
            )
            raise
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "control-mode client attached",
                extra={"tmux_cmd": shlex.join(argv), "tmux_session": target},
            )
        return link

    async def _await_attach(self, link: _Link) -> None:
        """Consume the attach acknowledgement, the connection's first block."""
        done, _ = await asyncio.wait({link.ack}, timeout=_STARTUP_TIMEOUT)
        if not done:
            msg = "tmux control-mode startup timed out"
            raise exc.ControlModeError(msg)
        outcome = link.ack.result()
        if isinstance(outcome, Exception):
            raise outcome
        if outcome.is_error:
            detail = b" ".join(outcome.body).decode("utf-8", "replace")
            msg = f"tmux control-mode attach failed: {detail}"
            raise exc.ControlModeError(msg)
        link.attached = True

    async def _handshake(self, link: _Link) -> None:
        """Set the client's flags and put back what subscribers rely on."""
        commands: list[CommandRequest] = []
        wants_output = bool(self._outputs or self._watches)
        self._silenced = not wants_output
        if not wants_output:
            commands.append(
                CommandRequest.from_args("refresh-client", "-f", "no-output"),
            )
        if self._pause_after is not None:
            commands.append(
                CommandRequest.from_args(
                    "refresh-client",
                    "-f",
                    f"pause-after={self._pause_after}",
                ),
            )
        if not commands:
            return
        payload = b"".join(protocol.encode_command(c.args) for c in commands)
        slots = self._submit(link, commands, payload)
        await self._drain(link)
        for command, slot in zip(commands, slots, strict=True):
            result = await self._collect(link, command, slot)
            if not result.ok:
                logger.warning(
                    "control-mode client flag was refused",
                    extra={"tmux_stderr": list(result.stderr)},
                )

    async def _teardown(
        self,
        link: _Link,
        reason: Exception,
        *,
        graceful: bool = False,
    ) -> None:
        """Detach the client, kill it if it lingers, and reap it.

        stdin is closed first so tmux detaches on its own; with *graceful* the
        reader keeps draining stdout for up to two seconds meanwhile, so tmux
        is never blocked writing to us. The reader is cancelled only once the
        client is gone or killed. A cancel that arrives while waiting does not
        skip the kill.
        """
        link.closing = True
        link.reaped = True  # this method reaps; _link_died must not also
        self._link_died(link, reason)  # fail what is owed with the right reason
        stdin = link.process.stdin
        if stdin is not None and not stdin.is_closing():
            stdin.close()
        tasks = [task for task in (link.reader, link.stderr_reader) if task]
        try:
            if graceful and link.process.returncode is None:
                await asyncio.wait(
                    {asyncio.ensure_future(link.process.wait())},
                    timeout=_DETACH_TIMEOUT,
                )
        finally:
            await _kill_and_reap_async(link.process, *tasks)

    # -- the reader ------------------------------------------------------

    async def _read(self, link: _Link) -> None:
        stdout = link.process.stdout
        assert stdout is not None
        failure: Exception | None = None
        try:
            while True:
                chunk = await stdout.read(_READ_CHUNK)
                if not chunk:
                    break
                for event in link.parser.feed(chunk):
                    self._handle(link, event)
                await asyncio.sleep(0)  # a flood must not starve the loop
        except exc.ControlProtocolError as error:
            failure = error
        finally:
            self._link_died(link, failure)

    async def _read_stderr(self, link: _Link) -> None:
        stderr = link.process.stderr
        assert stderr is not None
        while chunk := await stderr.read(4096):
            link.stderr += chunk
            del link.stderr[:-_STDERR_BYTES]

    def _handle(self, link: _Link, event: protocol.ControlEvent) -> None:
        if isinstance(event, protocol.Block):
            self._on_block(link, event)
        elif isinstance(event, protocol.Output):
            channel = self._outputs.get(event.pane)
            if channel is not None:
                channel._feed(event.data)
            for watch in self._watches.get(event.pane, ()):
                watch._feed()
        elif isinstance(event, protocol.Pause):
            channel = self._outputs.get(event.pane)
            if channel is not None:
                channel._pause_took_effect()
            self._publish(protocol.Notification("pause", event.pane))
        elif isinstance(event, protocol.Continue):
            channel = self._outputs.get(event.pane)
            if channel is not None:
                channel._continue_took_effect()
            self._publish(protocol.Notification("continue", event.pane))
        elif isinstance(event, protocol.Notification):
            self._publish(event)
        elif isinstance(event, protocol.SubscriptionChanged):
            args = (
                f"{event.name} {event.session} {event.window} "
                f"{event.window_index} {event.pane}"
            )
            self._publish(
                protocol.Notification(
                    "subscription-changed", f"{args} : {event.value}"
                ),
            )
        elif isinstance(event, protocol.Exit):
            self._publish(protocol.Notification("exit", event.reason or ""))

    def _on_block(self, link: _Link, block: protocol.Block) -> None:
        link.sequence.check(block)
        if not link.attached:
            if not link.ack.done():
                link.ack.set_result(block)
            return
        if not block.solicited:
            return  # a hook's command writes a block; nothing waits for it
        if not link.fifo:
            msg = "control-mode reply with no request waiting"
            raise exc.ControlProtocolError(msg)
        slot = link.fifo[0]
        slot.blocks.append(block)
        if block.is_error or len(slot.blocks) >= slot.expected:
            link.fifo.popleft()
            slot.finish(slot.blocks)

    def _publish(self, notification: protocol.Notification) -> None:
        for subscriber in self._subscribers:
            subscriber.push(notification)

    def _link_died(self, link: _Link, error: Exception | None) -> None:
        """Fail what the link owed and tell its subscribers. Idempotent."""
        if link.dead.is_set():
            return
        link.dead.set()
        if self._link is link:
            self._link = None
        outcome: Exception
        if isinstance(error, exc.EngineClosed) or error is not None:
            outcome = error
        else:
            outcome = self._lost(link)
        if not link.ack.done():
            link.ack.set_result(outcome)
        while link.fifo:
            link.fifo.popleft().finish(outcome)
        if not link.reaped:
            link.reaped = True
            task = asyncio.ensure_future(_kill_and_reap_async(link.process))
            self._background.add(task)
            task.add_done_callback(self._background.discard)
        if not (self._closed or link.closing):
            for channel in self._outputs.values():
                channel._lost()
            for watches in self._watches.values():
                for watch in watches:
                    watch._feed()
            self._demand.set()

    def _lost(self, link: _Link) -> exc.ControlConnectionLost:
        tail = link.stderr.decode("utf-8", "replace").splitlines()[-_STDERR_LINES:]
        detail = f": {' | '.join(tail)}" if tail else ""
        return exc.ControlConnectionLost(f"the control client exited{detail}")

    # -- supervision -----------------------------------------------------

    def _want_connection(self) -> None:
        """Start the supervisor: something now depends on the connection."""
        self._demand.set()
        if self._supervisor is None and not self._closed:
            self._supervisor = asyncio.ensure_future(self._supervise())

    def _has_subscribers(self) -> bool:
        return bool(self._subscribers or self._outputs or self._watches)

    async def _supervise(self) -> None:
        """Keep a connection up while anything depends on one.

        Reconnects with ``min(0.1 * 2**min(n, 6), 5.0)`` seconds between
        failed attempts, where ``n`` resets once a connection has lived a
        second. With nothing subscribed it does nothing, and the next request
        reconnects on demand.
        """
        failures = 0
        while not self._closed:
            link = self._link
            if link is not None and not link.dead.is_set():
                await link.dead.wait()
                failures = (
                    0 if time.monotonic() - link.born >= _STABLE_AFTER else failures + 1
                )
                continue
            if not self._has_subscribers():
                self._demand.clear()
                await self._demand.wait()
                continue
            if failures:
                await asyncio.sleep(
                    min(_BACKOFF_BASE * 2 ** min(failures, 6), _BACKOFF_CAP),
                )
            try:
                reconnected = self._generation > 0
                new = await self._ensure_link()
            except (exc.LibTmuxException, OSError):
                failures += 1
                continue
            if new is None:
                failures += 1
                continue
            if reconnected:
                self._publish(
                    protocol.Notification(RECONNECTED, str(self._generation)),
                )

    # -- sinks -----------------------------------------------------------

    def _drop_subscriber(self, subscriber: _Subscriber) -> None:
        with contextlib.suppress(ValueError):
            self._subscribers.remove(subscriber)

    def _drop_output(self, channel: OutputChannel) -> None:
        if self._outputs.get(channel.pane) is channel:
            del self._outputs[channel.pane]
            self._sinks_changed()

    def _drop_watch(self, watch: OutputWatch) -> None:
        watches = self._watches.get(watch.pane, [])
        with contextlib.suppress(ValueError):
            watches.remove(watch)
        if not watches:
            self._watches.pop(watch.pane, None)
        self._sinks_changed()

    def _sinks_changed(self) -> None:
        """Turn pane output on or off at tmux to match who is listening."""
        wants = bool(self._outputs or self._watches)
        if wants:
            self._want_connection()
        if wants == (not self._silenced):
            return
        self._silenced = not wants
        flag = "!no-output" if wants else "no-output"
        self._fire(CommandRequest.from_args("refresh-client", "-f", flag))

    def _flow(self, channel: OutputChannel, action: Action) -> None:
        """Send the pause or continue a channel's watermarks called for."""
        verb = "pause" if action is Action.PAUSE else "continue"
        done = (
            channel._pause_took_effect
            if action is Action.PAUSE
            else channel._continue_took_effect
        )
        self._fire(
            CommandRequest.from_args("refresh-client", "-A", f"{channel.pane}:{verb}"),
            callback=lambda _blocks: done(),
        )

    def _fire(
        self,
        request: CommandRequest,
        callback: t.Callable[[list[protocol.Block]], None] | None = None,
    ) -> None:
        """Send a command and ignore its reply, apart from *callback*."""
        link = self._link
        if link is None or link.dead.is_set() or not link.attached:
            return  # a new connection starts from known flags
        try:
            self._submit(
                link,
                [request],
                protocol.encode_command(request.args),
                [callback],
            )
        except exc.ControlConnectionLost:
            return
