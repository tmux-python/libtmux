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
  spawns ``tmux -C``, replays the desired subscriptions, and runs the reader
  inline (one reader at a time). When the reader returns on EOF, the supervisor
  resets connection-scoped state -- a fresh parser, failed pending commands,
  cleared attach -- bumps the connection generation, and reconnects with a
  deterministic jittered backoff, so a tmux restart or socket blip self-heals
  instead of freezing the engine. An intentional :meth:`aclose` flags
  ``_closing`` first so the close is not mistaken for a crash and retried.
- A reader failure or EOF marks the engine *dead* and fails every pending
  command, rather than hanging; the supervisor then reconnects.
- Notifications go to a bounded queue; on overflow the oldest is dropped and
  counted (backpressure), mirroring control mode's own ``%pause`` philosophy.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import typing as t
from dataclasses import dataclass, field

from libtmux import exc
from libtmux.experimental.engines.base import render_control_line
from libtmux.experimental.engines.connection import ServerConnection
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
# A connection must survive at least this long to count as healthy and reset the
# reconnect backoff; a shorter-lived one is treated as a failed attempt so a
# persistently flapping proc escalates instead of fork-storming.
_HEALTHY_CONNECTION_SECONDS = 1.0

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


def _swallow_future(future: asyncio.Future[t.Any]) -> None:
    """Retrieve a fire-and-forget future's outcome so it isn't flagged unretrieved.

    Subscription-replay commands are dispatched without an awaiter; their futures
    resolve in the reader. Calling :meth:`asyncio.Future.exception` marks the
    result retrieved so a tmux-side ``%error`` (or a reconnect that fails the
    pending command) never surfaces as a noisy "exception was never retrieved"
    warning.
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
        self._conn = ServerConnection.of(tmux_bin, server_args)
        self.timeout = timeout
        self._parser = ControlModeParser()
        self._pending: collections.deque[_PendingCommand] = collections.deque()
        self._event_queue_size = event_queue_size
        self._subscribers: set[asyncio.Queue[t.Any]] = set()
        self._dropped_notifications = 0
        self._proc: asyncio.subprocess.Process | None = None
        self._start_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._started = False
        self._dead: BaseException | None = None
        # Desired (declarative) state, replayed on every (re)connect.
        self._desired_subscriptions: list[str] = []
        self._desired_attach: list[str] = []
        self._attached_session: str | None = None
        # Supervisor / reconnect bookkeeping.
        self._generation = 0
        self._closing = False
        self._supervisor_task: asyncio.Task[None] | None = None
        self._connected = asyncio.Event()
        self._spawn_error: BaseException | None = None

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
        launches a second supervisor; all callers block until the first
        connection is established.
        """
        async with self._start_lock:
            if not self._started:
                self._closing = False
                self._spawn_error = None
                self._connected.clear()
                self._supervisor_task = asyncio.create_task(
                    self._supervisor(),
                    name="libtmux-async-control-supervisor",
                )
                self._started = True
        # Block (every caller) until the supervisor's first connect resolves.
        if self._supervisor_task is not None:
            await self._connected.wait()
            if self._spawn_error is not None:
                # Keep _spawn_error set here: a *concurrent* start() caller from
                # the same failed first connect must also observe it and raise,
                # not see a nulled error and return "success" against a dead
                # engine. The error is cleared only by the fresh-start reset
                # above (the `if not self._started` block) when a NEW attempt
                # begins, so every waiter from this failed connect raises
                # consistently.
                error = self._spawn_error
                async with self._start_lock:
                    self._started = False
                    self._supervisor_task = None
                raise error

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
        if old is not None and old.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                old.terminate()
        cmd = self._conn.argv("-C")
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
        # Keep the death-sentinel set while the startup ACK is consumed: across a
        # reconnect ``_connected`` stays set, so a concurrent ``run_batch`` would
        # otherwise pass the dead-guard, write to the new proc, and have its reply
        # DRAINED+DISCARDED by ``_consume_startup`` (its future then times out and
        # its stale pending entry desyncs FIFO). Clearing ``_dead`` only after the
        # ACK is consumed makes such a racing command hit the dead-guard instead.
        await self._consume_startup()
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

        A subscribe() *after* :meth:`aclose` (which set :attr:`_closing`,
        broadcast the stream-end sentinel, and cleared :attr:`_subscribers`)
        would register a fresh queue no broadcast will ever touch, hanging the
        consumer forever. So a permanently-closing engine yields nothing and
        ends at once. A merely :attr:`_dead` (reconnecting) engine keeps the
        subscriber, so the post-reconnect reader feeds it.
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
        the loop instead of triggering a reconnect.
        """
        if not self._started:
            return
        self._closing = True
        self._started = False
        supervisor = self._supervisor_task
        self._supervisor_task = None
        if supervisor is not None:
            supervisor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await supervisor
        # Release any start() still blocked on the first connection. The
        # supervisor's finally covers a normal exit, but a task cancelled before
        # it ever runs never reaches that finally, so set it here too.
        self._connected.set()
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

    async def _supervisor(self) -> None:
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
                        self._spawn_error = error
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
                await self._reap_own_session()
                await self._replay_subscriptions()
                await self._replay_attach()
                self._connected.set()  # first connect done: unblock start()
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
        finally:
            # Always release start() waiters -- even on cancel/return before the
            # first connect -- so an aclose() racing a start() can never leave a
            # waiter blocked on _connected.wait() forever.
            self._connected.set()

    async def _reap_own_session(self) -> None:
        """Mark this control client's throwaway session ``destroy-unattached``.

        A bare ``tmux -C`` connect implies ``new-session``, so each connection
        spawns a phantom session on the target server. Right after connect -- while
        the control client is still attached to that just-created session, before
        :meth:`_replay_attach` moves it -- this sets ``destroy-unattached on`` on
        the *current* session (the phantom; no ``-t`` and no ``-g``, so it is scoped
        to exactly that session, never global). tmux then reaps the phantom the
        moment the client attaches elsewhere or disconnects, so control-mode never
        litters the server with throwaway sessions and a reconnect storm cannot pile
        them up. Fire-and-forget, like :meth:`_replay_subscriptions` -- the result
        block is swallowed since the reader has not started yet.
        """
        proc = self._proc
        if proc is None or proc.stdin is None:
            return
        loop = asyncio.get_running_loop()
        argv = ("set-option", "destroy-unattached", "on")
        async with self._write_lock:
            future: asyncio.Future[CommandResult] = loop.create_future()
            future.add_done_callback(_swallow_future)
            self._pending.append(_PendingCommand(future, argv, command_count(argv)))
            try:
                proc.stdin.write((render_control_line(argv) + "\n").encode())
                await proc.stdin.drain()
            except (BrokenPipeError, OSError):
                # The proc died before the option landed; the reader will EOF and
                # the supervisor reconnects (the next connect re-marks its phantom).
                return

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

        Mirrors :meth:`_replay_subscriptions`. A fresh ``tmux -C`` process is
        attached to nothing, and per-pane ``%subscription-changed`` only flows
        to an *attached* control client, so the supervisor must re-attach after
        every (re)connect or a monitor that relies on the option channel goes
        silent. Each target is written as ``attach-session -t <target>`` directly
        to stdin with a swallowed pending future (same FIFO + :attr:`_write_lock`
        discipline as the subscription replay), so it re-enters neither
        :meth:`start` nor :meth:`run_batch`. A control client attaches to one
        session at a time, so the last target wins. The attach is fire-and-forget,
        so it does not cache :attr:`_attached_session` here; the events layer sets
        that on a confirmed attach and re-attaches on a miss. Does nothing when
        :attr:`_desired_attach` is empty.
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
                argv = ("attach-session", "-t", target)
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

        The events layer caches which session this engine attached to in
        :attr:`_attached_session`; a fresh process is attached to nothing, so the
        cache must be cleared on every (re)connect.
        """
        self._attached_session = None

    @staticmethod
    def _backoff(attempt: int) -> float:
        """Deterministic jittered exponential backoff (seconds) for *attempt*.

        Capped exponential (``min(0.1 * 2**attempt, 5.0)``) plus a small jitter
        derived solely from *attempt* -- never :mod:`random` or wall-clock time --
        so reconnect timing stays reproducible under test.
        """
        base = min(0.1 * (2.0**attempt), 5.0)
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
        conn = ServerConnection.from_server(server)
        return cls(
            tmux_bin=conn.tmux_bin,
            server_args=conn.args,
            **kwargs,
        )
