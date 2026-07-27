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
  desyncs. The startup ACK is consumed synchronously in :meth:`_spawn` before
  the reader runs, closing the startup race.
- A supervisor owns the process lifecycle. :meth:`start` launches it once; it
  attaches to an exact existing session without updating its environment,
  replays the desired subscriptions, and runs the reader inline (one reader at
  a time). When the reader returns on EOF, the supervisor resets
  connection-scoped state -- a fresh parser, failed pending commands, cleared
  attach -- bumps the connection generation, and reconnects with a deterministic
  jittered backoff, so a tmux restart or socket blip self-heals instead of
  freezing the engine. An intentional :meth:`aclose` flags ``_closing`` first so
  the close is not mistaken for a crash and retried.
- If no safe session exists yet, command batches use the native async
  subprocess engine. A command such as ``new-session`` can bootstrap the server
  without a throwaway control session; later batches can open the persistent
  client.
- A reader failure or EOF marks the engine *dead* and fails every pending
  command, rather than hanging; the supervisor then reconnects.
- Notifications go to a bounded queue; on overflow the oldest is dropped and
  counted (backpressure), mirroring control mode's own ``%pause`` philosophy.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import logging
import typing as t
from dataclasses import dataclass, field

from libtmux import exc
from libtmux.experimental.engines.asyncio import AsyncSubprocessEngine
from libtmux.experimental.engines.base import CommandRequest, render_control_line
from libtmux.experimental.engines.connection import ServerConnection
from libtmux.experimental.engines.control_mode import (
    BlockSequenceMonitor,
    ControlModeError,
    ControlModeParser,
    _merge_blocks,
    command_count,
)

if t.TYPE_CHECKING:
    import types
    from collections.abc import AsyncIterator, Sequence

    from typing_extensions import Self

    from libtmux.experimental.engines.base import CommandResult
    from libtmux.experimental.engines.control_mode import ControlModeBlock

logger = logging.getLogger(__name__)

_READ_CHUNK = 65536
_DEFAULT_TIMEOUT = 30.0
_STARTUP_TIMEOUT = 5.0
_STOP_TIMEOUT = 2.0
# A connection must survive at least this long to count as healthy and reset the
# reconnect backoff; a shorter-lived one is treated as a failed attempt so a
# persistently flapping proc escalates instead of fork-storming.
_HEALTHY_CONNECTION_SECONDS = 1.0

_STREAM_END = object()  # broadcast to subscriber queues to end their async for


@dataclass(frozen=True)
class ControlNotification:
    """An asynchronous tmux control-mode notification.

    Attributes
    ----------
    kind : str
        Notification name without the leading ``%``.
    args : tuple[str, ...]
        Whitespace-separated notification arguments.
    raw : str
        Decoded control-mode line before tokenization.

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
        body = text.removeprefix("%")
        parts = body.split(" ")
        kind = parts[0] if parts else ""
        return cls(kind=kind, args=tuple(parts[1:]), raw=text)


@dataclass(slots=True)
class _PendingCommand:
    """One command awaiting its control-mode response blocks.

    Attributes
    ----------
    future : asyncio.Future[CommandResult]
        Future completed when the expected blocks arrive.
    argv : tuple[str, ...]
        Rendered tmux command tokens.
    expected : int
        Number of response blocks required for completion.
    blocks : list[ControlModeBlock]
        Response blocks collected so far.
    """

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


def _swallow_future(future: asyncio.Future[t.Any]) -> None:
    """Retrieve an independently owned future so it isn't flagged unretrieved.

    Subscription replays have no awaiter, and every caller may cancel its wait
    on a shared start attempt. Calling :meth:`asyncio.Future.exception` marks
    either result retrieved without changing what a later ``result()`` observes.
    """
    if future.cancelled():
        return
    with contextlib.suppress(Exception):
        future.exception()


class AsyncControlModeEngine:
    """Execute tmux commands over one persistent async ``tmux -C`` connection.

    Parameters
    ----------
    tmux_bin : str or None
        The tmux binary; resolved from ``$PATH`` when ``None``.
    server_args : Sequence[str]
        Connection flags inserted before ``-C``.
    timeout : float
        Seconds to await a command's result before failing it.
    event_queue_size : int
        Bounded size of the notification queue (backpressure).

    Notes
    -----
    The connection opens on async context entry when a safe session exists, or
    on the first later command that finds one. Use the engine as an async context
    manager, or call :meth:`aclose`, to tear it down. Commands use async
    subprocess execution until an existing session has an effective
    ``destroy-unattached`` value of ``off``.
    """

    def __init__(
        self,
        tmux_bin: str | None = None,
        *,
        server_args: Sequence[str] = (),
        timeout: float = _DEFAULT_TIMEOUT,
        event_queue_size: int = 4096,
    ) -> None:
        self._conn = ServerConnection.of(tmux_bin, server_args)
        self.timeout = timeout
        self._parser = ControlModeParser()
        self._sequence = BlockSequenceMonitor()
        self._pending: collections.deque[_PendingCommand] = collections.deque()
        self._event_queue_size = event_queue_size
        self._subscribers: set[asyncio.Queue[t.Any]] = set()
        self._dropped_notifications = 0
        self._proc: asyncio.subprocess.Process | None = None
        self._start_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._started = False
        self._dead: BaseException | None = None
        self._bootstrap = AsyncSubprocessEngine(
            tmux_bin=self._conn.tmux_bin,
            server_args=self._conn.args,
        )
        self._bootstrap_tasks: set[asyncio.Task[list[CommandResult]]] = set()
        # Desired (declarative) state, replayed on every (re)connect.
        self._desired_subscriptions: list[str] = []
        self._desired_attach: list[str] = []
        self._attached_session: str | None = None
        # Supervisor / reconnect bookkeeping.
        self._generation = 0
        self._closing = False
        self._supervisor_task: asyncio.Task[None] | None = None
        self._start_attempt: asyncio.Future[None] | None = None
        self._next_attach_target: str | None = None

    @property
    def connection(self) -> ServerConnection:
        """The tmux binary + connection flags this engine dispatches through."""
        return self._conn

    @property
    def tmux_bin(self) -> str | None:
        """The explicitly configured tmux binary, if any."""
        return self._conn.tmux_bin

    @property
    def server_args(self) -> tuple[str, ...]:
        """Connection flags placed before ``-C``."""
        return self._conn.args

    def tmux_version(self) -> str | None:
        """Report the connected server's tmux version (``tmux -V``), memoized.

        Implements
        :class:`~libtmux.experimental.engines.base.SupportsTmuxVersion` so
        version-gated operations render correctly over control mode; in-memory
        engines omit it and resolution assumes latest.
        """
        return self._conn.tmux_version()

    def add_subscription(self, spec: str) -> None:
        """Record a desired ``refresh-client -B`` subscription (idempotent).

        The spec is stored in :attr:`_desired_subscriptions` and replayed on
        every (re)connect by the supervisor, so a subscription survives a tmux
        restart or socket blip. Adding the same spec twice is a no-op.

        Parameters
        ----------
        spec : str
            A ``refresh-client -B`` subscription spec, e.g.
            ``"agentstate:%*:#{@agent_state}"``.

        Examples
        --------
        >>> engine = AsyncControlModeEngine()
        >>> engine.add_subscription("agentstate:%*:#{@agent_state}")
        >>> engine.add_subscription("agentstate:%*:#{@agent_state}")
        >>> engine._desired_subscriptions
        ['agentstate:%*:#{@agent_state}']
        """
        if spec not in self._desired_subscriptions:
            self._desired_subscriptions.append(spec)

    def set_attach_targets(self, ids: list[str]) -> None:
        """Record the sessions the engine should (re)attach to on reconnect.

        Stores a *copy* of *ids* in :attr:`_desired_attach`. The supervisor
        replays these on every (re)connect via :meth:`_replay_attach`, so the
        engine stays attached across a tmux restart or socket blip (a control
        client attaches to one session at a time, so the last target wins).

        Parameters
        ----------
        ids : list[str]
            Session ids to attach to (e.g. ``["$0", "$1"]``).

        Examples
        --------
        >>> engine = AsyncControlModeEngine()
        >>> engine.set_attach_targets(["$0", "$1"])
        >>> engine._desired_attach
        ['$0', '$1']
        """
        self._desired_attach = list(ids)

    async def start(self) -> None:
        """Launch the supervisor (once) and wait for its first connection.

        The supervisor owns the ``tmux -C`` process lifecycle: it spawns the
        proc, consumes the startup ACK, replays desired subscriptions, runs the
        reader, and reconnects with backoff when the reader returns. This method
        is idempotent (the ``_start_lock`` + ``_started`` guard) and never
        launches a second supervisor; all callers block on the same immutable
        attempt. Direct startup requires an existing session whose effective
        ``destroy-unattached`` option is ``off``; :meth:`run_batch` uses
        subprocess execution while no such target exists.
        """
        async with self._start_lock:
            attempt = self._begin_start_locked()
        await self._wait_start_attempt(attempt)

    def _begin_start_locked(self) -> asyncio.Future[None]:
        """Return the current immutable start attempt, creating it if needed."""
        attempt: asyncio.Future[None] | None
        if not self._started:
            self._closing = False
            attempt = asyncio.get_running_loop().create_future()
            attempt.add_done_callback(_swallow_future)
            self._start_attempt = attempt
            self._supervisor_task = asyncio.create_task(
                self._supervisor(attempt),
                name="libtmux-async-control-supervisor",
            )
            self._started = True
        else:
            attempt = self._start_attempt
        if attempt is None:
            msg = "control-mode start attempt is unavailable"
            raise ControlModeError(msg)
        return attempt

    @staticmethod
    async def _wait_start_attempt(attempt: asyncio.Future[None]) -> None:
        """Wait without propagating caller cancellation into *attempt*.

        ``asyncio.shield`` creates an intermediate future whose exception can be
        reported as unretrieved when its only waiter is cancelled. Waiting on
        the shared future through ``asyncio.wait`` preserves its immutable result
        without creating that diagnostic-only wrapper.
        """
        await asyncio.wait((attempt,))
        attempt.result()

    async def _spawn(self) -> None:
        """Spawn a fresh ``tmux -C`` process and consume its startup ACK.

        Extracted from :meth:`start` so the supervisor can re-run it on every
        reconnect. Sets :attr:`_proc`, then clears :attr:`_dead` only *after* the
        startup ACK is consumed (so a command racing the reconnect still hits the
        dead-guard). The caller is responsible for resetting the parser *before*
        this runs, so the new process's startup bytes are parsed by a fresh parser.
        """
        # A reader that returned via an exception (not a clean EOF) leaves the
        # prior tmux -C alive; terminate it before overwriting _proc so a
        # reconnect never orphans a control client. A clean-EOF proc has already
        # exited, so this is a no-op there.
        old = self._proc
        if old is not None:
            await self._stop_process(old)
        target = self._next_attach_target
        self._next_attach_target = None
        if target is None:
            target = await self._find_attach_target()
        if target is None:
            msg = (
                "control mode requires an existing session whose effective "
                "destroy-unattached option is off"
            )
            raise ControlModeError(msg)
        cmd = self._conn.argv(
            "-C",
            "attach-session",
            "-E",
            "-t",
            target,
        )
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
        # Keep the death-sentinel set while the startup ACK is consumed. The
        # first-start future is already resolved during reconnects, so a racing
        # run_batch must hit the dead guard instead of writing a reply that
        # _consume_startup would drain and discard.
        try:
            await self._consume_startup()
        except BaseException:
            await self._stop_process(proc)
            self._proc = None
            raise
        self._dead = None

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
                msg = "tmux control-mode startup timed out"
                raise ControlModeError(msg)
            try:
                chunk = await asyncio.wait_for(
                    proc.stdout.read(_READ_CHUNK),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                msg = "tmux control-mode startup timed out"
                raise ControlModeError(msg) from None
            if not chunk:
                msg = "tmux -C closed stdout during startup"
                raise ControlModeError(msg)
            self._parser.feed(chunk)
            self._parser.notifications()  # discard any startup notifications
            discarded = self._parser.blocks()
            if discarded:
                if discarded[-1].is_error:
                    detail = "; ".join(
                        line.decode(errors="replace") for line in discarded[-1].body
                    )
                    msg = "tmux control-mode attach failed"
                    raise ControlModeError(f"{msg}: {detail}" if detail else msg)
                solicited = [block for block in discarded if block.flags == 1]
                if solicited:
                    # Anything but the ACK here is a command reply thrown away on
                    # the reconnect path -- the documented swallow risk.
                    logger.warning(
                        "control-mode startup consumed %s solicited block(s); "
                        "%s command(s) were pending",
                        len(solicited),
                        len(self._pending),
                        extra={
                            "tmux_stdout": [
                                f"#{block.number}: "
                                + b" | ".join(block.body).decode(errors="replace")
                                for block in solicited
                            ],
                            "tmux_stdout_len": len(solicited),
                        },
                    )
                return

    async def run(self, request: CommandRequest) -> CommandResult:
        """Execute one command through control mode or bootstrap subprocess."""
        return (await self.run_batch([request]))[0]

    async def run_batch(
        self, requests: Sequence[CommandRequest]
    ) -> list[CommandResult]:
        """Pipeline a batch, bootstrapping through subprocess when necessary."""
        if not requests:
            return []
        bootstrap: asyncio.Task[list[CommandResult]] | None = None
        attempt: asyncio.Future[None] | None = None
        async with self._start_lock:
            if self._bootstrap_tasks:
                bootstrap = self._begin_bootstrap_locked(requests)
            elif self._started and self._dead is not None:
                target = await self._find_attach_target()
                if target is None:
                    await self._close_locked()
                    bootstrap = self._begin_bootstrap_locked(requests)
            if bootstrap is None and not self._started:
                target = await self._find_attach_target()
                if target is None:
                    bootstrap = self._begin_bootstrap_locked(requests)
                else:
                    self._next_attach_target = target
            if bootstrap is None:
                attempt = self._begin_start_locked()
        if bootstrap is not None:
            return await bootstrap
        if attempt is None:
            msg = "control-mode dispatch attempt is unavailable"
            raise ControlModeError(msg)
        await self._wait_start_attempt(attempt)
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
            except asyncio.CancelledError:
                # ``write`` already accepted the payload. Keep its FIFO entries
                # so the reader can drain any replies, but make their futures
                # terminal so close/reconnect cannot publish unobserved errors.
                for queued in appended:
                    if not queued.future.done():
                        queued.future.cancel()
                raise
            except (BrokenPipeError, OSError) as error:
                # Remove the futures we just queued so a write failure cannot
                # leave orphans that desync FIFO correlation for the next batch.
                cm_error = ControlModeError(f"tmux control-mode write failed: {error}")
                for queued in appended:
                    with contextlib.suppress(ValueError):
                        self._pending.remove(queued)
                    if not queued.future.done():
                        queued.future.cancel()
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

    def _begin_bootstrap_locked(
        self,
        requests: Sequence[CommandRequest],
    ) -> asyncio.Task[list[CommandResult]]:
        """Start one tracked subprocess batch while lifecycle state is locked."""
        self._closing = False
        task = asyncio.create_task(
            self._bootstrap.run_batch(requests),
            name="libtmux-async-control-bootstrap",
        )
        self._bootstrap_tasks.add(task)
        task.add_done_callback(self._bootstrap_tasks.discard)
        return task

    async def subscribe(self) -> AsyncIterator[ControlNotification]:
        """Yield asynchronous tmux notifications as they arrive.

        Each subscriber gets its own queue, so concurrent subscribers (the event
        push tool, the pull ring, the output monitor) each see *every*
        notification rather than competing for one shared stream. The iterator
        runs until the engine is closed or the caller stops iterating; its queue
        is unregistered on exit. When the engine dies, ``_STREAM_END`` is
        broadcast to every subscriber queue so the ``async for`` ends cleanly
        instead of hanging on ``queue.get()``.

        A subscribe() *after* :meth:`aclose` (which set :attr:`_closing`,
        broadcast the stream-end sentinel, and cleared :attr:`_subscribers`)
        would register a fresh queue no broadcast will ever touch, hanging the
        consumer forever. So a permanently-closing engine yields nothing and
        ends at once. A reader death also closes the current stream; callers can
        subscribe again after the supervisor reconnects.
        """
        if self._closing:
            return
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
        """Tear down: flag closing, cancel the supervisor, fail pending, kill proc.

        Setting :attr:`_closing` *first* distinguishes an intentional close from a
        crash, so cancelling the supervisor (and the reader it owns inline) ends
        the loop instead of triggering a reconnect. The start lock covers the
        complete transition so a new supervisor cannot appear midway through
        close.
        """
        cleanup = asyncio.create_task(
            self._aclose_impl(),
            name="libtmux-async-control-close",
        )
        cancelled = await self._wait_for_close_cleanup(cleanup)
        cleanup.result()
        if cancelled:
            raise asyncio.CancelledError

    @staticmethod
    async def _wait_for_close_cleanup(cleanup: asyncio.Task[None]) -> bool:
        """Wait through every caller cancellation; report whether one occurred."""
        try:
            await asyncio.wait((cleanup,))
        except asyncio.CancelledError:
            # Recursion gives each accepted ``cancel()`` its own handler without
            # propagating cancellation into the independently owned cleanup task.
            await AsyncControlModeEngine._wait_for_close_cleanup(cleanup)
            return True
        return False

    async def _aclose_impl(self) -> None:
        """Serialize close and cancel every tracked subprocess bootstrap."""
        async with self._start_lock:
            self._closing = True
            bootstrap = tuple(self._bootstrap_tasks)
            for task in bootstrap:
                task.cancel()
            if bootstrap:
                await asyncio.gather(*bootstrap, return_exceptions=True)
            await self._close_locked()

    async def _close_locked(self) -> None:
        """Close while the caller holds :attr:`_start_lock`."""
        self._closing = True
        self._started = False
        supervisor = self._supervisor_task
        attempt = self._start_attempt
        self._next_attach_target = None
        if supervisor is not None:
            supervisor.cancel()
            await asyncio.wait((supervisor,))
            if not supervisor.cancelled():
                supervisor.result()
            if self._supervisor_task is supervisor:
                self._supervisor_task = None
        if attempt is not None and not attempt.done():
            attempt.set_exception(ControlModeError("control-mode engine closed"))
        if self._start_attempt is attempt:
            self._start_attempt = None
        self._broadcast_stream_end()
        self._fail_pending(ControlModeError("control-mode engine closed"))
        proc = self._proc
        if proc is not None:
            await self._stop_process(proc)
            if self._proc is proc:
                self._proc = None

    async def __aenter__(self) -> Self:
        """Start when a safe session exists; otherwise remain lazy to bootstrap."""
        attempt: asyncio.Future[None] | None = None
        async with self._start_lock:
            if self._started:
                attempt = self._begin_start_locked()
            else:
                target = await self._find_attach_target()
                if target is not None:
                    self._next_attach_target = target
                    attempt = self._begin_start_locked()
        if attempt is not None:
            await self._wait_start_attempt(attempt)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Close the engine on context exit."""
        await self.aclose()

    async def _supervisor(
        self,
        first_attempt: asyncio.Future[None] | None = None,
    ) -> None:
        """Own the proc lifecycle: connect, replay desired state, read, reconnect.

        One supervisor runs at a time (launched once by :meth:`start`). Each
        iteration resets connection-scoped state *before* the new process's bytes
        flow -- a fresh :class:`~.control_mode.ControlModeParser`, failed pending
        commands, cleared attach -- then spawns ``tmux -C``, bumps
        :attr:`_generation`, replays subscriptions, and runs the reader inline so
        there is never more than one reader. When the reader returns on EOF (and
        the engine is not :attr:`_closing`), it backs off with deterministic
        jitter and reconnects. An intentional :meth:`aclose` cancels this task,
        which propagates into the inline reader.
        """
        attempt = 0
        connected_once = False
        try:
            while not self._closing:
                # Reset connection-scoped state BEFORE the new proc's bytes flow.
                # Reconnect is the only place permitted to reset the parser and
                # fail pending, keeping FIFO correlation aligned across the gap.
                self._parser = ControlModeParser()
                self._sequence.reset()
                self._fail_pending(ControlModeError("control-mode reconnecting"))
                self._reset_attach()
                try:
                    await self._spawn()
                except asyncio.CancelledError:
                    raise
                except BaseException as error:
                    if not connected_once:
                        # First connect failed (e.g. missing binary): surface it
                        # to start() and stop -- a permanent error should not spin.
                        await self._finish_failed_start(first_attempt, error)
                        return
                    # A transient spawn failure mid-life: back off and retry.
                    await asyncio.sleep(self._backoff(attempt))
                    attempt += 1
                    continue
                # The spawn succeeded and its startup ACK was consumed. Do NOT
                # reset the backoff yet: a proc that connects then immediately
                # dies (reader EOF within the grace) is not a healthy session, and
                # resetting here would pin every reconnect at _backoff(0) and
                # fork-storm tmux. The reset is gated on connection lifetime below.
                self._generation += 1
                connected_once = True
                await self._replay_subscriptions()
                await self._replay_attach()
                if first_attempt is not None and not first_attempt.done():
                    first_attempt.set_result(None)
                # The reader runs inline (one reader at a time). On EOF it returns
                # and we reconnect; on cancellation (aclose) it propagates out.
                loop = asyncio.get_running_loop()
                connected_at = loop.time()
                await self._reader()
                if self._closing:
                    return
                # Only a connection that survived a meaningful interval resets the
                # backoff; a connect-then-immediately-die counts as a failed
                # attempt, so a persistently flapping proc escalates instead of
                # spinning at _backoff(0).
                if loop.time() - connected_at >= _HEALTHY_CONNECTION_SECONDS:
                    attempt = 0
                await asyncio.sleep(self._backoff(attempt))
                attempt += 1
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            failure = ControlModeError(f"control-mode supervisor failed: {error}")
            self._mark_dead(failure)
            proc = self._proc
            if proc is not None:
                try:
                    await self._stop_process(proc)
                except Exception as cleanup_error:
                    failure = ControlModeError(
                        f"control-mode supervisor failed: {error}; "
                        f"process cleanup failed: {cleanup_error}"
                    )
                else:
                    if self._proc is proc:
                        self._proc = None
            await self._finish_failed_start(first_attempt, failure)
        finally:
            if first_attempt is not None and not first_attempt.done():
                first_attempt.set_exception(
                    ControlModeError("control-mode engine closed before connecting"),
                )

    async def _finish_failed_start(
        self,
        attempt: asyncio.Future[None] | None,
        error: BaseException,
    ) -> None:
        """Publish one failed attempt and make a later call eligible to retry."""
        if attempt is None:
            return
        async with self._start_lock:
            if self._start_attempt is attempt:
                self._started = False
                self._start_attempt = None
                if self._supervisor_task is asyncio.current_task():
                    self._supervisor_task = None
            if not attempt.done():
                attempt.set_exception(error)

    async def _find_attach_target(self) -> str | None:
        """Return an exact session id whose effective detach policy is off."""
        sessions = await self._bootstrap.run(
            CommandRequest.from_args("list-sessions", "-F", "#{session_id}"),
        )
        if sessions.returncode != 0:
            return None
        for session_id in sessions.stdout:
            option = await self._bootstrap.run(
                CommandRequest.from_args(
                    "show-options",
                    "-Av",
                    "-t",
                    session_id,
                    "destroy-unattached",
                ),
            )
            if option.returncode == 0 and option.stdout == ("off",):
                return session_id
        return None

    @staticmethod
    async def _stop_process(proc: asyncio.subprocess.Process) -> None:
        """Terminate and reap *proc*, escalating after a bounded wait."""
        if proc.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=_STOP_TIMEOUT)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            try:
                await asyncio.wait_for(proc.wait(), timeout=_STOP_TIMEOUT)
            except asyncio.TimeoutError:
                msg = "tmux control process did not exit after kill"
                raise ControlModeError(msg) from None

    async def _replay_subscriptions(self) -> None:
        """Re-issue every desired subscription to the freshly connected proc.

        Each spec is sent as ``refresh-client -B <spec>`` with a queued pending
        command, so the reader correlates its result block in FIFO order (the
        replay commands sit at the front of the deque, ahead of any user command,
        because :meth:`start` has not yet returned). The futures are
        fire-and-forget: their outcome is swallowed rather than awaited, since the
        reader has not started yet. Writing here re-enters neither :meth:`start`
        nor :meth:`run_batch`, so the supervisor cannot recurse into itself.
        """
        if not self._desired_subscriptions:
            return
        proc = self._proc
        if proc is None or proc.stdin is None:
            return
        loop = asyncio.get_running_loop()
        async with self._write_lock:
            payload_parts: list[bytes] = []
            for spec in self._desired_subscriptions:
                argv = ("refresh-client", "-B", spec)
                future: asyncio.Future[CommandResult] = loop.create_future()
                future.add_done_callback(_swallow_future)
                self._pending.append(_PendingCommand(future, argv, command_count(argv)))
                payload_parts.append((render_control_line(argv) + "\n").encode())
            try:
                proc.stdin.write(b"".join(payload_parts))
                await proc.stdin.drain()
            except (BrokenPipeError, OSError):
                # The proc died before replay landed; the reader will EOF and the
                # supervisor reconnects, failing these pending commands then.
                return

    async def _replay_attach(self) -> None:
        """Re-attach to every desired session on the freshly connected proc.

        Mirrors :meth:`_replay_subscriptions`. The process initially attaches to
        an existing session; this replay switches it to each requested target
        with ``-E`` so the last target wins without applying
        ``update-environment``. Each command is written directly to stdin with a
        swallowed pending future, so it re-enters neither :meth:`start` nor
        :meth:`run_batch`. The fire-and-forget replay does not cache
        :attr:`_attached_session`; the events layer sets that only after a
        confirmed attach. Does nothing when :attr:`_desired_attach` is empty.
        """
        if not self._desired_attach:
            return
        proc = self._proc
        if proc is None or proc.stdin is None:
            return
        loop = asyncio.get_running_loop()
        async with self._write_lock:
            payload_parts: list[bytes] = []
            for target in self._desired_attach:
                argv = ("attach-session", "-E", "-t", target)
                future: asyncio.Future[CommandResult] = loop.create_future()
                future.add_done_callback(_swallow_future)
                self._pending.append(_PendingCommand(future, argv, command_count(argv)))
                payload_parts.append((render_control_line(argv) + "\n").encode())
            try:
                proc.stdin.write(b"".join(payload_parts))
                await proc.stdin.drain()
            except (BrokenPipeError, OSError):
                # The proc died before replay landed; the reader will EOF and the
                # supervisor reconnects, failing these pending commands then.
                return
            # The attach is fire-and-forget (swallowed future): its returncode is
            # not awaited, so _attached_session is NOT cached optimistically here.
            # The events layer caches it only on a confirmed attach and re-attaches
            # on a miss, so a session that vanished during the disconnect surfaces a
            # real error instead of a silently-empty capture.

    def _reset_attach(self) -> None:
        """Clear the sticky attach so reconnect re-attaches from scratch.

        The events layer caches a confirmed requested target in
        :attr:`_attached_session`. A fresh process starts on the engine's safe
        bootstrap session, not necessarily that requested target, so the cache
        is cleared on every reconnect.
        """
        self._attached_session = None

    @staticmethod
    def _backoff(attempt: int) -> float:
        """Deterministic jittered exponential backoff (seconds) for *attempt*.

        Capped exponential growth plus a small jitter derived solely from
        *attempt* -- never :mod:`random` or wall-clock time -- so reconnect
        timing stays finite and reproducible under test.
        """
        base = min(0.1 * (2.0 ** min(attempt, 6)), 5.0)
        jitter = 0.01 * float(attempt % 7)
        return base + jitter

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
            # A solicited reply with no command waiting: its command's future was
            # already resolved, cancelled, or failed. FIFO is now one block off.
            logger.warning(
                "control-mode dropped solicited block #%s with no pending command",
                block.number,
                extra={
                    "tmux_stdout": [
                        line.decode(errors="replace") for line in block.body
                    ],
                    "tmux_stdout_len": len(block.body),
                },
            )
            return
        pending = self._pending[0]
        self._sequence.check(block, pending.argv)
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
        conn = ServerConnection.from_server(server)
        return cls(
            tmux_bin=conn.tmux_bin,
            server_args=conn.args,
            **kwargs,
        )
