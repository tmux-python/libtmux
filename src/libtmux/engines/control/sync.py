"""A synchronous control-mode engine: one persistent ``tmux -C`` client.

:class:`ControlModeEngine` replaces a fork per command with one long-lived
``tmux -C attach-session`` client. Commands go down its stdin as quoted lines
and replies come back as ``%begin``/``%end`` blocks, which
:mod:`~libtmux.engines.control.protocol` frames. Median latency drops from
roughly 3.5 ms to 0.3 ms and the tmux process count from one per command to
one.

The driver owns one thread, the caller's: it writes with a selector and reads
until the replies it is waiting for have arrived. Nothing reads between calls,
so the client asks tmux not to send pane output at all
(``refresh-client -f no-output``). Otherwise a pane printing faster than the
application calls the engine would fill the pipe and stall.
"""

from __future__ import annotations

import collections
import contextlib
import logging
import os
import selectors
import shlex
import subprocess
import threading
import time
import typing as t

from libtmux import exc
from libtmux.engines.base import CommandRequest, CommandResult, command_count
from libtmux.engines.connection import ServerConnection
from libtmux.engines.control import protocol
from libtmux.engines.control.routing import blocks_queue
from libtmux.engines.subprocess import SubprocessEngine

if t.TYPE_CHECKING:
    import types
    from collections.abc import Sequence

    from typing_extensions import Self

logger = logging.getLogger(__name__)

_READ_CHUNK = 65536
_STARTUP_TIMEOUT = 5.0
_DETACH_TIMEOUT = 2.0
_KILL_TIMEOUT = 2.0
_STDERR_LINES = 20
_STDERR_BYTES = 16384
_OFF_VALUES = frozenset({"off", "0"})


class _Expired(Exception):
    """Internal: a wait for tmux outlasted its deadline."""


class ControlModeEngine:
    """Run tmux commands over one persistent control-mode client.

    The client attaches to an existing session whose ``destroy-unattached``
    option is off; a bare ``tmux -C`` would create a throwaway session on the
    server. While no such session exists, requests run in a subprocess, and the
    first request after one appears opens the connection. Commands that wait
    (``run-shell``, ``wait-for``, ``confirm-before``, a non-detached
    ``new-session``) always run in a subprocess, because one waiting command
    would hold every command behind it.

    Parameters
    ----------
    tmux_bin : str, optional
        The tmux binary; resolved from ``$PATH`` when omitted.
    server_args : sequence of str
        Connection flags, such as ``("-Lwork",)``.

    Notes
    -----
    Calls are serialised: one thread at a time owns the connection. A request
    that finds the client gone raises
    :exc:`~libtmux.exc.ControlConnectionLost`, and the next request reconnects.
    Call :meth:`close` or use the engine as a context manager.

    Examples
    --------
    >>> from libtmux.engines import CommandRequest
    >>> from libtmux.engines.control.sync import ControlModeEngine
    >>> engine = ControlModeEngine.for_server(server)
    >>> with engine:
    ...     engine.run(CommandRequest.from_args("display-message", "-p", "hi")).stdout
    ('hi',)
    """

    def __init__(
        self,
        tmux_bin: str | None = None,
        *,
        server_args: Sequence[str] = (),
    ) -> None:
        self._conn = ServerConnection.of(tmux_bin, server_args)
        self._subprocess = SubprocessEngine(self._conn)
        self._lock = threading.RLock()
        self._closed = False
        self._generation = 0
        self._proc: subprocess.Popen[bytes] | None = None
        self._selector: selectors.BaseSelector | None = None
        self._parser = protocol.ControlModeParser()
        self._sequence = protocol.BlockSequenceMonitor()
        self._replies: collections.deque[protocol.Block] = collections.deque()
        self._stderr = bytearray()
        self._exited = False
        self._attached = False
        self._skip = 0

    @classmethod
    def for_server(cls, server: t.Any) -> Self:
        """Build an engine bound to a live :class:`libtmux.Server`'s socket.

        Examples
        --------
        >>> ControlModeEngine.for_server(server).server_args[0].startswith("-L")
        True
        """
        conn = ServerConnection.from_server(server)
        return cls(conn.tmux_bin, server_args=conn.args)

    def with_connection(self, connection: ServerConnection) -> ControlModeEngine:
        """Return an equivalent, unconnected engine bound to *connection*.

        :attr:`Server.engine <libtmux.Server.engine>` calls this to bind an
        engine that names no server of its own.

        Examples
        --------
        >>> from libtmux.engines import ServerConnection
        >>> ControlModeEngine().with_connection(
        ...     ServerConnection.of(args=("-Lwork",))
        ... ).server_args
        ('-Lwork',)
        """
        return type(self)(connection.tmux_bin, server_args=connection.args)

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
        >>> ControlModeEngine().generation
        0
        """
        return self._generation

    def tmux_version(self) -> str | None:
        """Report the tmux version this engine targets (memoized)."""
        return self._conn.tmux_version()

    def command_line(self, request: CommandRequest) -> tuple[str, ...]:
        """Return the argv a subprocess would run for *request*.

        A control request has no argv of its own; this is the equivalent
        command line, which is what :attr:`CommandResult.cmd` reports.
        """
        return self._subprocess.command_line(request)

    # -- public API ------------------------------------------------------

    def run(self, request: CommandRequest) -> CommandResult:
        """Run one command and return its result.

        Raises
        ------
        ~libtmux.exc.EngineClosed
            The engine was closed.
        ~libtmux.exc.ControlConnectionLost
            The control client exited before replying.
        ~libtmux.exc.ControlProtocolError
            tmux's output was malformed; the connection is discarded.
        ~libtmux.exc.TmuxCommandNotFound
            The tmux binary is missing.
        """
        return self.run_batch([request])[0]

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Run requests in order, pipelining those that share the connection.

        Consecutive control-eligible requests are written together and their
        replies read back in order. A request that must run in a subprocess
        ends the pipeline, runs, and a new pipeline starts after it.

        Returns
        -------
        list of CommandResult
            One result per request.
        """
        results: list[CommandResult] = []
        pipeline: list[CommandRequest] = []
        for request in requests:
            if blocks_queue(request.args) or request.input is not None:
                results += self._run_pipeline(pipeline)
                pipeline = []
                results.append(self._run_subprocess(request))
            else:
                pipeline.append(request)
        results += self._run_pipeline(pipeline)
        return results

    def close(self) -> None:
        """Detach the control client and reap it. Safe to call twice."""
        with self._lock:
            self._closed = True
            self._teardown(graceful=True)

    def __enter__(self) -> Self:
        """Return this engine."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Close the engine."""
        self.close()

    # -- routing ---------------------------------------------------------

    def _run_subprocess(self, request: CommandRequest) -> CommandResult:
        with self._lock:
            self._raise_if_closed()
        return self._subprocess.run(request)

    def _run_pipeline(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        if not requests:
            return []
        # Encode everything first: an argument tmux cannot be sent must fail
        # before any reply slot exists for it.
        lines = [protocol.encode_command(request.args) for request in requests]
        with self._lock:
            self._raise_if_closed()
            if not self._ensure_connected():
                return [self._subprocess.run(request) for request in requests]
            try:
                return self._exchange(requests, b"".join(lines))
            except (exc.ControlConnectionLost, exc.ControlProtocolError):
                self._teardown(graceful=False)
                raise

    def _raise_if_closed(self) -> None:
        if self._closed:
            msg = "the control-mode engine is closed"
            raise exc.EngineClosed(msg)

    # -- connection ------------------------------------------------------

    def _ensure_connected(self) -> bool:
        """Open the connection if needed; ``False`` when no session can host it."""
        proc = self._proc
        if proc is not None and proc.poll() is None and not self._exited:
            return True
        if proc is not None:
            self._teardown(graceful=False)
        target = self._find_attach_target()
        if target is None:
            return False
        self._start(target)
        return True

    def _find_attach_target(self) -> str | None:
        """Return a session id whose ``destroy-unattached`` is already off.

        Reads only: nothing about any session's options is changed, so opening
        the connection cannot cause a session to be destroyed.
        """
        listing = self._subprocess.run(
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

    def _start(self, target: str) -> None:
        argv = self._conn.argv("-u", "-C", "attach-session", "-E", "-t", target)
        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except FileNotFoundError:
            raise exc.TmuxCommandNotFound from None
        assert proc.stdin is not None
        assert proc.stdout is not None
        assert proc.stderr is not None
        for stream in (proc.stdout, proc.stderr):
            os.set_blocking(stream.fileno(), False)
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ, "stdout")
        selector.register(proc.stderr, selectors.EVENT_READ, "stderr")
        self._proc = proc
        self._selector = selector
        self._parser = protocol.ControlModeParser()
        self._sequence.reset()
        self._replies.clear()
        self._stderr.clear()
        self._exited = False
        self._attached = False
        self._skip = 0
        self._generation += 1
        try:
            self._await_attach(time.monotonic() + _STARTUP_TIMEOUT)
            self._attached = True
            self._silence_output()
        except BaseException:
            self._teardown(graceful=False)
            raise
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "control-mode client attached",
                extra={"tmux_cmd": shlex.join(argv), "tmux_session": target},
            )

    def _await_attach(self, deadline: float) -> None:
        """Consume the attach acknowledgement, the connection's first block."""
        try:
            block = self._next_reply(deadline)
        except _Expired:
            msg = "tmux control-mode startup timed out"
            raise exc.ControlModeError(msg) from None
        if block.is_error:
            detail = b" ".join(block.body).decode("utf-8", "replace")
            msg = f"tmux control-mode attach failed: {detail}"
            raise exc.ControlModeError(msg)

    def _silence_output(self) -> None:
        """Ask tmux for no pane output, which this driver never reads."""
        request = CommandRequest.from_args("refresh-client", "-f", "no-output")
        (result,) = self._exchange([request], protocol.encode_command(request.args))
        if not result.ok:
            logger.warning(
                "control-mode client could not silence pane output",
                extra={"tmux_stderr": list(result.stderr)},
            )

    def _teardown(self, *, graceful: bool) -> None:
        proc, selector = self._proc, self._selector
        self._proc = None
        self._selector = None
        self._replies.clear()
        self._skip = 0
        if selector is not None:
            with contextlib.suppress(Exception):
                selector.close()
        if proc is None:
            return
        if proc.stdin is not None:
            with contextlib.suppress(OSError):
                proc.stdin.close()
        exited = proc.poll() is not None
        if not exited and graceful:
            exited = _wait(proc, _DETACH_TIMEOUT)
        if not exited:
            with contextlib.suppress(OSError):
                proc.kill()
            _wait(proc, _KILL_TIMEOUT)
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                with contextlib.suppress(OSError):
                    stream.close()

    # -- exchange --------------------------------------------------------

    def _exchange(
        self,
        requests: Sequence[CommandRequest],
        payload: bytes,
    ) -> list[CommandResult]:
        """Write *payload*, then read one result per request, in order."""
        proc = self._proc
        assert proc is not None
        assert proc.stdin is not None
        # Writing blocks until tmux has read it all. tmux buffers its replies
        # without bound, so a batch bigger than the pipe cannot deadlock the
        # two sides (20 MB each way measured on 3.2a and 3.8-rc).
        view = memoryview(payload)
        try:
            while view:
                view = view[os.write(proc.stdin.fileno(), view) :]
        except BrokenPipeError:
            self._exited = True
            self._read_stderr()
            raise self._lost() from None
        results: list[CommandResult] = []
        try:
            for request in requests:
                results.append(self._collect(request))  # noqa: PERF401
        except exc.TmuxTimeout:
            self._abandon(requests[len(results) :])
            raise
        return results

    def _collect(self, request: CommandRequest) -> CommandResult:
        """Read the reply blocks one request produces and merge them."""
        expected = command_count(request.args)
        deadline = (
            None if request.timeout is None else time.monotonic() + request.timeout
        )
        blocks: list[protocol.Block] = []
        while len(blocks) < expected:
            try:
                block = self._next_reply(deadline)
            except _Expired:
                assert request.timeout is not None
                logger.error(  # noqa: TRY400
                    "tmux control command timed out",
                    extra={
                        "tmux_cmd": shlex.join(self.command_line(request)),
                        "tmux_timeout": request.timeout,
                    },
                )
                raise exc.TmuxTimeout(
                    cmd=list(self.command_line(request)),
                    timeout=request.timeout,
                ) from None
            blocks.append(block)
            if block.is_error:
                break  # tmux drops the rest of a failed command group
        return self._result(request, blocks)

    def _abandon(self, outstanding: Sequence[CommandRequest]) -> None:
        """Give up on replies still owed, keeping the connection aligned.

        A single command owes exactly one block, so its reply can be consumed
        and dropped when it arrives. A command group owes between one and its
        length, depending on where an error stops it, so the count is unknown
        and the connection is discarded instead; the next call reconnects.
        """
        if any(command_count(request.args) != 1 for request in outstanding):
            self._teardown(graceful=False)
            return
        for _ in outstanding:
            if self._replies:
                self._replies.popleft()
            else:
                self._skip += 1

    def _next_reply(self, deadline: float | None) -> protocol.Block:
        while not self._replies:
            if self._exited:
                raise self._lost()
            if not self._pump(deadline):
                raise _Expired
        return self._replies.popleft()

    def _result(
        self,
        request: CommandRequest,
        blocks: Sequence[protocol.Block],
    ) -> CommandResult:
        stdout: list[str] = []
        stderr: list[str] = []
        failed = False
        for block in blocks:
            lines = [line.decode("utf-8", "backslashreplace") for line in block.body]
            if block.is_error:
                failed = True
                # tmux prefixes a command it could not parse with "parse
                # error: " on a control client only; the CLI prints the bare
                # message, which is what every other engine reports.
                lines[:1] = [lines[0].removeprefix("parse error: ")] if lines else []
                stderr += [line for line in lines if line]
            else:
                stdout += lines
        while stdout and stdout[-1] == "":
            stdout.pop()
        cmd = self.command_line(request)
        result = CommandResult(
            cmd=cmd,
            stdout=tuple(stdout),
            stderr=tuple(stderr),
            returncode=1 if failed else 0,
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "tmux control command completed",
                extra={
                    "tmux_cmd": shlex.join(cmd),
                    "tmux_subcommand": request.subcommand,
                    "tmux_exit_code": result.returncode,
                    "tmux_stdout_len": len(result.stdout),
                    "tmux_stderr_len": len(result.stderr),
                },
            )
        return result

    def _pump(self, deadline: float | None) -> bool:
        """Wait for output from tmux and read it; ``False`` if time ran out."""
        selector = self._selector
        assert selector is not None
        timeout = None if deadline is None else max(0.0, deadline - time.monotonic())
        events = selector.select(timeout)
        for key, _ in events:
            if key.data == "stdout":
                self._read_stdout()
            else:
                self._read_stderr()
        return bool(events) or deadline is None

    def _read_stdout(self) -> None:
        proc = self._proc
        assert proc is not None
        assert proc.stdout is not None
        try:
            chunk = os.read(proc.stdout.fileno(), _READ_CHUNK)
        except BlockingIOError:
            return
        if not chunk:
            self._exited = True
            self._read_stderr()
            return
        for event in self._parser.feed(chunk):
            if isinstance(event, protocol.Block):
                self._sequence.check(event)
                # After the attach acknowledgement only replies to this
                # client's own commands matter; a hook's command also writes
                # a block, and no request is waiting for it.
                if event.solicited and self._skip:
                    self._skip -= 1  # the reply to an abandoned request
                elif event.solicited or not self._attached:
                    self._replies.append(event)
            elif isinstance(event, protocol.Exit):
                self._exited = True
                self._read_stderr()

    def _read_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        with contextlib.suppress(BlockingIOError, OSError):
            self._stderr += os.read(proc.stderr.fileno(), _READ_CHUNK)
            del self._stderr[:-_STDERR_BYTES]

    def _lost(self) -> exc.ControlConnectionLost:
        tail = self._stderr.decode("utf-8", "replace").splitlines()[-_STDERR_LINES:]
        detail = f": {' | '.join(tail)}" if tail else ""
        return exc.ControlConnectionLost(f"the control client exited{detail}")


def _wait(proc: subprocess.Popen[bytes], timeout: float) -> bool:
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return True
