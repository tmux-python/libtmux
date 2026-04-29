"""Persistent ``tmux -C`` control-mode engine implementation.

One ``ControlModeEngine`` instance pairs with one tmux server (one
``socket_name`` / ``socket_path``). The engine is lazy: the first
:meth:`ControlModeEngine.run` call spawns ``tmux -C <socket-flags>``
with separate stdin/stdout pipes, kicks off a daemon reader thread,
and from then on every command flows through that single child.

The reader thread owns the read side end-to-end:

* It drives a :mod:`selectors` loop on the stdout fd.
* Bytes are fed into a :class:`~libtmux.engines.control_mode.parser.ControlParser`.
* :class:`~libtmux.engines.control_mode.parser.Block` events are
  routed to a per-engine response :class:`queue.Queue`, which the
  blocking ``run()`` call pops.
* :class:`~libtmux.engines.control_mode.parser.Notification` events
  are DEBUG-logged here; the subscription dispatcher in step 5 will
  route them to user-facing queues.

Cleanup is defence-in-depth (step 4 of the plan):

#. Explicit :meth:`ControlModeEngine.close` — the recommended path.
   Sends the empty-line ``CLIENT_EXIT`` signal documented in
   ``control.c:551``, escalating through stdin-EOF, ``SIGTERM`` and
   ``SIGKILL``.
#. :func:`weakref.finalize` registered when the subprocess spawns —
   reaps the child + reader thread at GC time even when the user
   forgets to call ``close()``.
#. The reader thread is a free function (not a bound method); it
   intentionally does **not** capture the engine, so dropping the
   user's reference makes the engine collectible.
"""

from __future__ import annotations

import contextlib
import logging
import os
import pathlib
import queue
import selectors
import shlex
import shutil
import subprocess
import threading
import typing as t
import weakref
from dataclasses import dataclass, field

from libtmux import exc
from libtmux.engines.base import CommandRequest, CommandResult
from libtmux.engines.control_mode.parser import (
    Block,
    ControlParser,
    Notification,
    SubscriptionChangedNotification,
)
from libtmux.engines.control_mode.subscription import (
    _DEFAULT_MAXSIZE,
    Subscription,
)
from libtmux.engines.registry import register_engine

logger = logging.getLogger(__name__)


_DEFAULT_RUN_TIMEOUT = 30.0
"""Wall time to wait for a single command's response, in seconds.

Generous because tmux is local and most commands return in <100ms;
the cap is a safety net against hangs from a wedged server.
"""

_STARTUP_TIMEOUT = 5.0
"""Wall time to wait for tmux's startup ``%begin``/``%end`` ack."""

_READ_CHUNK = 65536
"""Size of each ``os.read`` from the tmux ``-C`` stdout pipe."""

_SELECT_TIMEOUT = 0.1
"""Selector timeout in seconds; bounds shutdown latency for the reader."""

_GLOBAL_FLAGS_WITH_VALUES: frozenset[str] = frozenset({"-L", "-S", "-f"})
"""tmux client-level flags that take a value (`-L socket`, `-S path`, `-f cfg`)."""

_GLOBAL_FLAGS_NOVALUE: frozenset[str] = frozenset({"-2", "-8"})
"""tmux client-level flags that take no value."""

_GRACEFUL_EXIT_TIMEOUT = 0.5
"""Seconds to wait for tmux to exit after the empty-line CLIENT_EXIT signal."""

_TERMINATE_TIMEOUT = 1.0
"""Seconds to wait after SIGTERM before escalating to SIGKILL."""


class TmuxControlModeError(exc.LibTmuxException):
    """The control-mode connection broke or could not be established."""


@dataclass(frozen=True, slots=True)
class _ParsedRequest:
    """Result of splitting a :class:`CommandRequest` for control-mode dispatch."""

    global_args: tuple[str, ...]
    """Pre-spawn flags: ``-L``/``-S``/``-f``/``-2``/``-8`` and their values."""

    command_argv: tuple[str, ...]
    """The command + args to write on the spawned client's stdin."""


@dataclass(slots=True)
class _ReaderError:
    """Sentinel placed on the response queue when the reader thread dies."""

    cause: BaseException


@dataclass(slots=True)
class _Subprocess:
    """Owned subprocess + reader bookkeeping kept off ControlModeEngine itself.

    Held under ``ControlModeEngine._lock`` whenever it is accessed from
    outside the reader thread.
    """

    proc: subprocess.Popen[bytes]
    selector: selectors.DefaultSelector
    reader: threading.Thread
    stop_event: threading.Event
    parser: ControlParser
    response_queue: queue.Queue[Block | _ReaderError] = field(
        default_factory=queue.Queue,
    )
    broken: TmuxControlModeError | None = None
    global_args: tuple[str, ...] = ()
    subscribers: dict[str, Subscription] = field(default_factory=dict)
    """Active subscriptions keyed by name.

    Reader thread reads, engine adds/removes. CPython's GIL makes
    dict get/set atomic, but iteration during modification is not
    safe — we never iterate the live dict (we only ever look up by
    name).
    """


class ControlModeEngine:
    """Persistent ``tmux -C`` engine.

    Parameters
    ----------
    tmux_bin : str or pathlib.Path, optional
        Override for ``shutil.which("tmux")``. Memoised after first
        resolution.
    run_timeout : float, optional
        Wall-clock cap for a single command's response. Defaults to
        :data:`_DEFAULT_RUN_TIMEOUT`. ``run()`` raises
        :class:`TmuxControlModeError` if no response arrives in time.

    Notes
    -----
    The engine binds to one tmux server. The socket is taken from the
    first ``run()`` call's ``-L`` / ``-S`` flags; subsequent calls
    must agree, otherwise the engine raises rather than silently
    forwarding to the wrong server.
    """

    def __init__(
        self,
        tmux_bin: str | pathlib.Path | None = None,
        *,
        run_timeout: float = _DEFAULT_RUN_TIMEOUT,
    ) -> None:
        self.tmux_bin = str(tmux_bin) if tmux_bin is not None else None
        self._run_timeout = run_timeout
        self._lock = threading.Lock()
        self._state: _Subprocess | None = None
        self._finalizer: weakref.finalize[t.Any, t.Any] | None = None
        self._resolved_default_tmux_bin: str | None = None

    # ------------------------------------------------------------- lookup --

    def _resolve_default_tmux_bin(self) -> str:
        """Return a memoised ``shutil.which("tmux")``.

        Mirrors the cache shape of
        :class:`~libtmux.engines.subprocess.SubprocessEngine` so
        downstream conftests can reset both engines uniformly.
        """
        if self._resolved_default_tmux_bin is None:
            resolved = shutil.which("tmux")
            if resolved is None:
                raise exc.TmuxCommandNotFound
            self._resolved_default_tmux_bin = resolved
        return self._resolved_default_tmux_bin

    # ---------------------------------------------------------- arg split --

    @staticmethod
    def _parse_args(args: tuple[str, ...]) -> _ParsedRequest:
        """Split ``args`` into pre-spawn client flags and post-spawn command.

        Recognises the same client-level flags as
        :class:`~libtmux.engines.imsg.ImsgEngine`. Anything not on the
        client-flag list — including the first non-flag token — starts
        the command portion that gets written on stdin after spawn.
        """
        global_args: list[str] = []
        command_argv: list[str] = []

        index = 0
        while index < len(args):
            arg = args[index]
            if arg == "-V":
                # tmux -V prints version and exits — never makes sense to
                # send through a persistent control client.
                command_argv.append(arg)
                break
            if arg in _GLOBAL_FLAGS_WITH_VALUES:
                if index + 1 >= len(args):
                    command_argv.append(arg)
                    break
                global_args.extend((arg, args[index + 1]))
                index += 2
                continue
            if arg in _GLOBAL_FLAGS_NOVALUE:
                global_args.append(arg)
                index += 1
                continue
            if len(arg) > 2 and arg[0] == "-" and arg[1] in {"L", "S", "f"}:
                # `-Lname`, `-Spath`, `-fcfg` (no separator).
                global_args.append(arg)
                index += 1
                continue
            command_argv.extend(args[index:])
            break

        return _ParsedRequest(
            global_args=tuple(global_args),
            command_argv=tuple(command_argv),
        )

    # ------------------------------------------------------------ run() --

    def run(self, request: CommandRequest) -> CommandResult:
        """Execute *request* on the persistent control-mode client.

        Spawns the subprocess on first call; reuses it thereafter.
        Concurrent calls serialise on a per-engine lock so the
        ``%begin``/``%end`` correlation stays one-in-flight.
        """
        parsed = self._parse_args(request.args)
        if not parsed.command_argv:
            msg = "ControlModeEngine.run requires a tmux subcommand"
            raise exc.LibTmuxException(msg)

        with self._lock:
            state = self._ensure_started(request, parsed)
            if state.broken is not None:
                raise state.broken
            self._send_command(state, parsed)
            response = self._await_response(state)

        return self._build_result(request, parsed, response)

    # ---------------------------------------------------------- internals --

    def _ensure_started(
        self,
        request: CommandRequest,
        parsed: _ParsedRequest,
    ) -> _Subprocess:
        """Lazy-spawn the subprocess on first command, reuse afterwards.

        A broken engine refuses to silently respawn: the user must
        call :meth:`close` (which discards the broken state) or
        construct a fresh engine. This avoids hiding connection
        instability from callers — a SIGKILL'd tmux server is a
        signal worth surfacing.
        """
        if self._state is not None:
            if self._state.broken is not None:
                raise self._state.broken
            if self._state.proc.poll() is not None:
                # Subprocess died without our reader noticing yet — surface as
                # a broken-engine error rather than silently respawning.
                err = TmuxControlModeError(
                    f"tmux -C exited with code {self._state.proc.returncode}",
                )
                _mark_broken(self._state, err)
                raise err
            if parsed.global_args != self._state.global_args:
                msg = (
                    "ControlModeEngine bound to global args "
                    f"{self._state.global_args!r}; refusing call with "
                    f"{parsed.global_args!r}"
                )
                raise TmuxControlModeError(msg)
            return self._state

        tmux_bin = request.tmux_bin or self.tmux_bin or self._resolve_default_tmux_bin()
        cmd = [tmux_bin, *parsed.global_args, "-C"]
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except FileNotFoundError:
            raise exc.TmuxCommandNotFound from None

        if proc.stdout is None or proc.stdin is None or proc.stderr is None:
            # Defensive — Popen with all three set to PIPE always populates
            # these. Treat as a hard failure rather than typing-only.
            with contextlib.suppress(OSError):
                proc.kill()
            msg = "tmux -C subprocess pipes are unset"
            raise TmuxControlModeError(msg)

        os.set_blocking(proc.stdout.fileno(), False)
        os.set_blocking(proc.stderr.fileno(), False)

        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ, "stdout")
        selector.register(proc.stderr, selectors.EVENT_READ, "stderr")

        stop_event = threading.Event()
        state = _Subprocess(
            proc=proc,
            selector=selector,
            # Reader is wired below so it can reference ``state`` without
            # capturing ``self`` — the latter would defeat
            # ``weakref.finalize`` by keeping the engine alive.
            reader=threading.Thread(),
            stop_event=stop_event,
            parser=ControlParser(),
            global_args=parsed.global_args,
        )
        state.reader = threading.Thread(
            target=_reader_loop,
            args=(state,),
            name=f"libtmux-cm-reader-{proc.pid}",
            daemon=True,
        )
        self._state = state
        # The reader thread reads ``self._state`` once, then operates on its
        # local handle; safe even if we later replace ``self._state``.
        state.reader.start()
        # Defence-in-depth: if the engine is garbage-collected without an
        # explicit close(), this finalizer reaps the subprocess + reader
        # thread at GC time. The closure intentionally takes no reference
        # to ``self`` so the engine is collectible.
        self._finalizer = weakref.finalize(self, _shutdown_subprocess, state)
        logger.debug(
            "tmux control-mode subprocess started",
            extra={
                "tmux_cm_proc_pid": proc.pid,
                "tmux_cmd": shlex.join(cmd),
            },
        )
        self._drain_startup_ack(state)
        return state

    def _drain_startup_ack(self, state: _Subprocess) -> None:
        """Discard the cfg-load ``%begin``/``%end`` tmux emits on connect.

        The startup ack has ``flags=0`` (not from a control client per
        ``cmd-queue.c:618``). Any later block our user requests has
        ``flags=1``; that distinction lets us drain exactly one
        startup block without consuming a real response. If the ack
        does not arrive within :data:`_STARTUP_TIMEOUT`, we mark the
        engine broken so the user's first ``run()`` reports a clean
        error rather than a mysterious empty result.
        """
        try:
            event = state.response_queue.get(timeout=_STARTUP_TIMEOUT)
        except queue.Empty:
            err = TmuxControlModeError(
                f"tmux -C did not send a startup ack within {_STARTUP_TIMEOUT}s",
            )
            _mark_broken(state, err)
            return
        if isinstance(event, _ReaderError):
            return
        if event.flags != 0:
            # Unexpected: the first block was apparently a real response,
            # which would only happen if the user's run() raced past us
            # — log loudly so this isn't silently dropped.
            logger.warning(
                "tmux control-mode dropped non-startup block during init",
                extra={
                    "tmux_cm_block_id": event.number,
                    "tmux_cm_proc_pid": state.proc.pid,
                },
            )

    def _send_command(
        self,
        state: _Subprocess,
        parsed: _ParsedRequest,
    ) -> None:
        line = (shlex.join(parsed.command_argv) + "\n").encode("utf-8")
        try:
            assert state.proc.stdin is not None
            state.proc.stdin.write(line)
            state.proc.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            _mark_broken(state, error)
            assert state.broken is not None
            raise state.broken from error

    def _await_response(self, state: _Subprocess) -> Block:
        try:
            event = state.response_queue.get(timeout=self._run_timeout)
        except queue.Empty as error:
            msg = (
                "tmux control-mode timed out after "
                f"{self._run_timeout}s waiting for a response"
            )
            err = TmuxControlModeError(msg)
            _mark_broken(state, err)
            raise err from error

        if isinstance(event, _ReaderError):
            assert state.broken is not None
            raise state.broken from event.cause
        return event

    def _build_result(
        self,
        request: CommandRequest,
        parsed: _ParsedRequest,
        block: Block,
    ) -> CommandResult:
        cmd_view = [
            request.tmux_bin or self.tmux_bin or "tmux",
            *parsed.global_args,
            *parsed.command_argv,
        ]
        body_lines = [b.decode("utf-8", errors="replace") for b in block.body]
        if block.is_error:
            return CommandResult(
                cmd=cmd_view,
                stdout=[],
                stderr=body_lines,
                returncode=1,
            )
        return CommandResult(
            cmd=cmd_view,
            stdout=body_lines,
            stderr=[],
            returncode=0,
        )

    # ----------------------------------------------------------- subscribe --

    def subscribe(
        self,
        name: str,
        fmt: str,
        *,
        target: str | None = None,
        maxsize: int = _DEFAULT_MAXSIZE,
    ) -> Subscription:
        """Subscribe to a tmux format and return a :class:`Subscription`.

        Issues ``refresh-client -B <name>:<target>:<fmt>`` against the
        running control client, registers a local routing entry, and
        returns the user-facing handle. Drop-oldest semantics on the
        queue keep the reader thread non-blocking.

        Notes
        -----
        ``target`` is one of ``None`` (session), ``"%*"`` (all panes),
        ``"%<id>"``, ``"@*"`` (all windows), ``"@<id>"`` (per
        ``cmd-refresh-client.c:65-74``).
        """
        sub = Subscription(
            name=name,
            fmt=fmt,
            target=target,
            queue=queue.Queue(maxsize=maxsize),
            _engine_ref=weakref.ref(self),
        )

        # Register *before* sending the wire command so any change
        # notification the server emits as a side effect of subscribing
        # has a destination. The reader thread routes by name; if the
        # name isn't yet registered the value is dropped.
        with self._lock:
            state = self._state
            if state is None or state.broken is not None:
                msg = (
                    "ControlModeEngine.subscribe requires an active "
                    "subprocess; call run() at least once first"
                )
                raise TmuxControlModeError(msg)
            state.subscribers[name] = sub

        target_str = target if target is not None else ""
        spec = f"{name}:{target_str}:{fmt}"
        try:
            request = CommandRequest.from_args(
                *state.global_args,
                "refresh-client",
                "-B",
                spec,
            )
            result = self.run(request)
        except BaseException:
            # Wire call failed — undo the local registration so the
            # caller doesn't end up with a phantom subscription.
            with self._lock:
                state.subscribers.pop(name, None)
            raise

        if result.returncode != 0:
            with self._lock:
                state.subscribers.pop(name, None)
            msg = "tmux refresh-client -B failed: " + " ".join(result.stderr)
            raise TmuxControlModeError(msg)
        return sub

    def _unregister_subscription(self, sub: Subscription) -> None:
        """Tear down a :class:`Subscription` initiated by :meth:`subscribe`.

        Sends the unsubscribe wire command (``refresh-client -B
        <name>`` with no colons, per ``cmd-refresh-client.c:55``)
        and removes the local routing entry. Errors are suppressed:
        an unsubscribe is best-effort by the time the user is asking
        the engine to forget about it.
        """
        with self._lock:
            state = self._state
            if state is not None:
                state.subscribers.pop(sub.name, None)

        if state is None or state.broken is not None:
            return
        with contextlib.suppress(BaseException):
            self.run(
                CommandRequest.from_args(
                    *state.global_args,
                    "refresh-client",
                    "-B",
                    sub.name,
                ),
            )

    # ----------------------------------------------------------- close --

    def _teardown_state(self) -> None:
        """Best-effort cleanup of the prior subprocess + reader thread.

        Detaches the ``weakref.finalize`` callback before tearing down
        so the engine can be re-spawned (e.g. after :meth:`close`)
        without a stale finalizer reaping the next subprocess.
        """
        state = self._state
        if state is None:
            return
        self._state = None
        if self._finalizer is not None:
            self._finalizer.detach()
            self._finalizer = None
        _shutdown_subprocess(state)

    def close(self) -> None:
        """Shut down the persistent subprocess and reader thread.

        Idempotent. Safe to call from ``Server.kill_server`` paths or
        from test teardown. Uses graceful escalation:

        1. Send the empty-line ``CLIENT_EXIT`` signal documented in
           ``control.c:551``.
        2. Wait :data:`_GRACEFUL_EXIT_TIMEOUT` for tmux to exit.
        3. Close stdin (EOF) and wait again.
        4. Send ``SIGTERM``, wait :data:`_TERMINATE_TIMEOUT`.
        5. Send ``SIGKILL`` as the final fallback.

        Defence-in-depth: even if the caller forgets ``close()``, the
        :class:`weakref.finalize` registered in
        :meth:`_ensure_started` performs the same teardown when the
        engine is garbage-collected.
        """
        with self._lock:
            self._teardown_state()


def _reader_loop(state: _Subprocess) -> None:
    """Daemon loop that drains stdout into the parser and routes events.

    Free-standing (not a method) so the thread does **not** capture a
    reference to the owning :class:`ControlModeEngine`. That decoupling
    is what lets :func:`weakref.finalize` actually fire on engine GC.
    """
    proc = state.proc
    selector = state.selector
    parser = state.parser
    stop_event = state.stop_event

    try:
        while not stop_event.is_set():
            try:
                ready = selector.select(_SELECT_TIMEOUT)
            except (OSError, ValueError):
                return
            if not ready:
                if proc.poll() is not None:
                    parser.feed_eof()
                    _mark_broken(
                        state,
                        TmuxControlModeError(
                            f"tmux -C exited with code {proc.returncode}",
                        ),
                    )
                    _drain_events(state)
                    return
                continue
            for key, _events in ready:
                if key.data == "stdout":
                    if not _reader_handle_stdout(state):
                        return
                elif key.data == "stderr":
                    _reader_handle_stderr(state)
            _drain_events(state)
    except Exception as error:  # pragma: no cover - last-ditch safety net
        _mark_broken(state, error)
        logger.exception(
            "tmux control-mode reader thread crashed",
            extra={"tmux_cm_proc_pid": proc.pid},
        )


def _reader_handle_stdout(state: _Subprocess) -> bool:
    assert state.proc.stdout is not None
    try:
        chunk = os.read(state.proc.stdout.fileno(), _READ_CHUNK)
    except BlockingIOError:
        return True
    except OSError as error:
        _mark_broken(state, error)
        return False
    if not chunk:
        state.parser.feed_eof()
        _mark_broken(state, TmuxControlModeError("tmux -C closed stdout"))
        _drain_events(state)
        return False
    state.parser.feed(chunk)
    return True


def _reader_handle_stderr(state: _Subprocess) -> None:
    assert state.proc.stderr is not None
    try:
        chunk = os.read(state.proc.stderr.fileno(), _READ_CHUNK)
    except (BlockingIOError, OSError):
        return
    if not chunk:
        return
    logger.debug(
        "tmux control-mode stderr",
        extra={
            "tmux_cm_proc_pid": state.proc.pid,
            "tmux_cm_stderr": chunk[:200],
        },
    )


def _drain_events(state: _Subprocess) -> None:
    for event in state.parser.events():
        if isinstance(event, Block):
            state.response_queue.put(event)
        elif isinstance(event, SubscriptionChangedNotification):
            sub = state.subscribers.get(event.name)
            if sub is not None:
                sub._deliver(event.value)
            else:
                logger.debug(
                    "tmux control-mode unrouted subscription",
                    extra={
                        "tmux_cm_notify": "SubscriptionChangedNotification",
                        "tmux_cm_subscription": event.name,
                        "tmux_cm_proc_pid": state.proc.pid,
                    },
                )
        elif isinstance(event, Notification):
            logger.debug(
                "tmux control-mode notification",
                extra={
                    "tmux_cm_notify": type(event).__name__,
                    "tmux_cm_proc_pid": state.proc.pid,
                },
            )


def _mark_broken(state: _Subprocess, cause: BaseException) -> None:
    """Latch *state* into a permanently-broken state and wake any waiter.

    Subsequent ``run()`` calls raise the latched error rather than
    attempting a respawn, so the caller can decide to retry by
    constructing a new engine or calling :meth:`ControlModeEngine.close`
    first.
    """
    if state.broken is not None:
        return
    if isinstance(cause, TmuxControlModeError):
        state.broken = cause
    else:
        state.broken = TmuxControlModeError(
            f"tmux control-mode connection lost: {cause}",
        )
    state.response_queue.put(_ReaderError(cause=cause))


def _shutdown_subprocess(state: _Subprocess) -> None:
    """Tear down a control-mode subprocess + its reader thread.

    Free-standing so it can be used as a :func:`weakref.finalize`
    callback (which must not capture a strong reference to the engine
    that owns the state).
    """
    state.stop_event.set()

    # 1. Empty-line CLIENT_EXIT (control.c:551) — graceful path.
    if state.proc.stdin is not None and not state.proc.stdin.closed:
        with contextlib.suppress(OSError):
            state.proc.stdin.write(b"\n")
            state.proc.stdin.flush()

    if not _wait_for_exit(state.proc, _GRACEFUL_EXIT_TIMEOUT):
        # 2. EOF on stdin — secondary graceful signal.
        if state.proc.stdin is not None and not state.proc.stdin.closed:
            with contextlib.suppress(OSError):
                state.proc.stdin.close()
        if not _wait_for_exit(state.proc, _GRACEFUL_EXIT_TIMEOUT):
            # 3. SIGTERM.
            with contextlib.suppress(OSError):
                state.proc.terminate()
            if not _wait_for_exit(state.proc, _TERMINATE_TIMEOUT):
                # 4. SIGKILL — last resort.
                with contextlib.suppress(OSError):
                    state.proc.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    state.proc.wait(timeout=_TERMINATE_TIMEOUT)

    # Close every pipe file object we own. Without this CPython emits
    # ``ResourceWarning: unclosed file`` at GC time for stdout/stderr,
    # because ``Popen.terminate``/``kill`` only signal the child — the
    # Python-side ``BufferedReader`` wrappers are independent.
    for stream in (state.proc.stdin, state.proc.stdout, state.proc.stderr):
        if stream is not None and not stream.closed:
            with contextlib.suppress(OSError):
                stream.close()

    with contextlib.suppress(OSError):
        state.selector.close()

    # Joining the reader thread from itself would raise; only join when
    # called from a different thread (e.g. explicit close() from main).
    if state.reader.is_alive() and threading.get_ident() != state.reader.ident:
        state.reader.join(timeout=_TERMINATE_TIMEOUT)


def _wait_for_exit(proc: subprocess.Popen[bytes], timeout: float) -> bool:
    """Return ``True`` if *proc* exited within *timeout* seconds."""
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return True


register_engine("control_mode", ControlModeEngine)
