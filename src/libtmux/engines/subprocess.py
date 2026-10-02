"""The default engine: one ``fork``/``exec`` of the tmux CLI per command.

Mirrors the output handling libtmux has always had -- ``backslashreplace``
decoding, trailing-blank stripping on stdout, blank filtering on stderr. A
tmux-side failure comes back as data (nonzero ``returncode`` plus ``stderr``);
only a missing binary raises.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shlex
import signal
import subprocess
import typing as t

from libtmux import exc
from libtmux.engines.base import CommandRequest, CommandResult
from libtmux.engines.connection import ServerConnection

if t.TYPE_CHECKING:
    import pathlib
    import types
    from collections.abc import Sequence

    from typing_extensions import Self

logger = logging.getLogger(__name__)

_REAP_TIMEOUT = 5.0


def _kill_and_reap(process: subprocess.Popen[t.Any]) -> None:
    """Kill a subprocess that outstayed its timeout, then reap it.

    :meth:`subprocess.Popen.communicate` leaves the child running when its
    *timeout* expires -- the caller has to kill and reap it, the same dance
    :func:`subprocess.run` does on its own timeout path. Skipping it leaks one
    tmux process per expiry.

    The child is waited for rather than drained: after ``SIGKILL`` it exits
    promptly, while reading its pipes to EOF could block on a grandchild that
    inherited them -- past the bound the caller just asked to enforce. The
    pipes are closed by hand instead, since nothing will read them.

    Examples
    --------
    >>> import sys
    >>> process = subprocess.Popen(
    ...     [sys.executable, '-c', 'import time; time.sleep(300)'],
    ...     stdout=subprocess.PIPE,
    ...     stderr=subprocess.PIPE,
    ... )
    >>> process.poll() is None  # still running
    True

    >>> _kill_and_reap(process)
    >>> process.returncode is not None  # dead, and its exit status collected
    True
    """
    process.kill()
    process.wait()
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            stream.close()


def _decode_text(data: bytes) -> str:
    r"""Decode tmux output as text mode does: UTF-8, universal newlines.

    Examples
    --------
    >>> _decode_text(b"a\r\nb\rc\xff")
    'a\nb\nc\\xff'
    """
    text = data.decode("utf-8", errors="backslashreplace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def run_argv(cmd: tuple[str, ...], request: CommandRequest) -> CommandResult:
    """Run *cmd* as a child process and return the structured result.

    The one place a tmux client is forked, shared by every engine that runs a
    local process: :class:`SubprocessEngine` passes the tmux argv, and
    :class:`~libtmux.engines.exec.ExecEngine` passes it behind a transport such
    as ``docker exec``. *request* supplies the stdin payload and the timeout.

    Parameters
    ----------
    cmd : tuple of str
        The full argv, program first.
    request : CommandRequest
        The request, for ``input``, ``timeout`` and log context.

    Returns
    -------
    CommandResult
        Output and exit status; a failure is data.

    Raises
    ------
    :exc:`~libtmux.exc.TmuxCommandNotFound`
        The program in ``cmd[0]`` is missing or not executable.
    :exc:`~libtmux.exc.TmuxTimeout`
        ``request.timeout`` elapsed; the child was killed and reaped.
    """
    process: subprocess.Popen[str] | subprocess.Popen[bytes] | None = None
    try:
        if request.input is None:
            text_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="backslashreplace",
            )
            process = text_process
            stdout, stderr = text_process.communicate(timeout=request.timeout)
        else:
            # Bytes cannot go through a text-mode pipe, so this branch
            # reads binary and decodes the way text mode does.
            payload = (
                request.input.encode("utf-8")
                if isinstance(request.input, str)
                else request.input
            )
            binary_process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            process = binary_process
            raw_out, raw_err = binary_process.communicate(
                payload,
                timeout=request.timeout,
            )
            stdout = _decode_text(raw_out)
            stderr = _decode_text(raw_err)
        returncode = process.returncode
    except FileNotFoundError:
        raise exc.TmuxCommandNotFound from None
    except subprocess.TimeoutExpired:
        assert process is not None
        assert request.timeout is not None
        _kill_and_reap(process)
        logger.error(  # noqa: TRY400
            "tmux command timed out",
            extra={
                "tmux_cmd": shlex.join(cmd),
                "tmux_timeout": request.timeout,
            },
        )
        raise exc.TmuxTimeout(cmd=list(cmd), timeout=request.timeout) from None
    except Exception:
        logger.error(  # noqa: TRY400
            "tmux subprocess failed",
            extra={"tmux_cmd": shlex.join(cmd)},
        )
        raise

    return _build_result(cmd, request, stdout, stderr, returncode, process)


def _build_result(
    cmd: tuple[str, ...],
    request: CommandRequest,
    stdout: str,
    stderr: str,
    returncode: int,
    process: subprocess.Popen[str] | subprocess.Popen[bytes] | None,
) -> CommandResult:
    r"""Shape a finished client's text output into a :class:`CommandResult`.

    Shared by the blocking and asyncio runners, so both report the same lines
    for the same bytes: trailing blanks off stdout, blank lines off stderr.

    Examples
    --------
    >>> from libtmux.engines import CommandRequest
    >>> _build_result(
    ...     ("tmux", "x"),
    ...     CommandRequest.from_args("x"),
    ...     "a\nb\n\n",
    ...     "\nboom\n",
    ...     1,
    ...     None,
    ... )
    CommandResult(cmd=('tmux', 'x'), stdout=('a', 'b'), stderr=('boom',), returncode=1)
    """
    stdout_lines = stdout.split("\n")
    while stdout_lines and stdout_lines[-1] == "":
        stdout_lines.pop()

    result = CommandResult(
        cmd=cmd,
        stdout=tuple(stdout_lines),
        stderr=tuple(line for line in stderr.split("\n") if line),
        returncode=returncode,
        process=process,
    )
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "tmux subprocess completed",
            extra={
                "tmux_cmd": shlex.join(cmd),
                "tmux_subcommand": request.subcommand,
                "tmux_exit_code": returncode,
                "tmux_stdout_len": len(result.stdout),
                "tmux_stderr_len": len(result.stderr),
            },
        )
    return result


def _kill_group(process: asyncio.subprocess.Process) -> None:
    """Send ``SIGKILL`` to a client's whole process group, if it still runs.

    The async runner starts every client in its own session, so the group is
    the client and anything it spawned: the ``docker`` or ``ssh`` program an
    exec transport runs dies with it instead of outliving the call. A client
    that has already been reaped is left alone, since its pid may be reused.
    """
    if process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(ProcessLookupError):
        process.kill()


async def _kill_and_reap_async(
    process: asyncio.subprocess.Process,
    *tasks: asyncio.Future[t.Any],
) -> None:
    """Kill a client, stop *tasks* that serve it, and wait for the reap.

    The kill is synchronous, so nothing can interrupt it. The waits that
    follow are repeated until they finish: a task cancelled once while it is
    cleaning up must still finish the cleanup, or the call that was cancelled
    leaves a zombie behind. Cancellations that arrive during a wait are held
    and re-raised afterwards, so the caller still sees one.

    Examples
    --------
    >>> import asyncio, sys
    >>> async def demo():
    ...     process = await asyncio.create_subprocess_exec(
    ...         sys.executable, "-c", "import time; time.sleep(300)",
    ...         start_new_session=True,
    ...     )
    ...     await _kill_and_reap_async(process)
    ...     return process.returncode
    >>> asyncio.run(demo())
    -9
    """
    _kill_group(process)
    for task in tasks:
        task.cancel()
    cancelled: asyncio.CancelledError | None = None
    for task in tasks:
        while not task.done():
            try:
                await asyncio.wait({task})
            except asyncio.CancelledError as error:  # noqa: PERF203
                cancelled = error
        if not task.cancelled():
            task.exception()  # mark retrieved; neither task raises
    # Process.wait() also waits for the client's pipes to close. A descendant
    # that escaped the group and still holds one would stall it forever, so the
    # wait is bounded; the client itself is already dead by then.
    waiter = asyncio.ensure_future(process.wait())
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _REAP_TIMEOUT
    while not waiter.done() and loop.time() < deadline:
        try:
            await asyncio.wait({waiter}, timeout=max(deadline - loop.time(), 0))
        except asyncio.CancelledError as error:  # noqa: PERF203
            cancelled = error
    if not waiter.done():
        logger.warning(
            "tmux client was killed but its pipes are still open",
            extra={"tmux_pid": process.pid},
        )
        waiter.cancel()
        while not waiter.done():
            try:
                await asyncio.wait({waiter})
            except asyncio.CancelledError as error:  # noqa: PERF203
                cancelled = error
    if not waiter.cancelled():
        waiter.exception()
    # wait() returns when the process exits, which can be before the loop has
    # read the end of its pipes. Close stdin and read stdout and stderr to the
    # end, so the pipe transports are closed when this returns instead of
    # being left to the garbage collector.
    if process.stdin is not None:
        with contextlib.suppress(Exception):
            process.stdin.close()
    for stream in (process.stdout, process.stderr):
        if stream is None:
            continue
        drain = asyncio.ensure_future(stream.read())
        while not drain.done() and loop.time() < deadline:
            try:
                await asyncio.wait({drain}, timeout=max(deadline - loop.time(), 0))
            except asyncio.CancelledError as error:  # noqa: PERF203
                cancelled = error
        if not drain.done():
            drain.cancel()
            while not drain.done():
                try:
                    await asyncio.wait({drain})
                except asyncio.CancelledError as error:  # noqa: PERF203
                    cancelled = error
        if not drain.cancelled():
            drain.exception()
    # A descendant that escaped the group can still hold a pipe open, so the
    # reads above may have run out of time. Close what is left rather than
    # leave a transport for the garbage collector.
    transport = getattr(process, "_transport", None)
    if transport is not None:
        for fd in (0, 1, 2):
            pipe = transport.get_pipe_transport(fd)
            if pipe is not None and not pipe.is_closing():
                pipe.close()
    if cancelled is not None:
        raise cancelled


async def _reap_spawn(spawn: asyncio.Future[asyncio.subprocess.Process]) -> None:
    """Wait out a spawn whose caller was cancelled, then reap what it started."""
    cancelled: asyncio.CancelledError | None = None
    while not spawn.done():
        try:
            await asyncio.wait({spawn})
        except asyncio.CancelledError as error:  # noqa: PERF203
            cancelled = error
    if not spawn.cancelled() and spawn.exception() is None:
        await _kill_and_reap_async(spawn.result())
    if cancelled is not None:
        raise cancelled


async def spawn_async(
    cmd: tuple[str, ...],
    *,
    stdin: int,
) -> asyncio.subprocess.Process:
    """Start *cmd* as a client in its own session, with piped output.

    The one place an async engine starts a tmux client. The spawn is shielded:
    a task cancelled while the child is being created waits for it to exist,
    kills and reaps it, and only then lets the cancellation through, so a
    cancel cannot orphan a client that was half started.

    Parameters
    ----------
    cmd : tuple of str
        The full argv, program first.
    stdin : int
        ``asyncio.subprocess.PIPE`` or ``asyncio.subprocess.DEVNULL``.

    Raises
    ------
    :exc:`~libtmux.exc.TmuxCommandNotFound`
        The program in ``cmd[0]`` is missing or not executable.
    :exc:`asyncio.CancelledError`
        The caller was cancelled; nothing it started is left running.

    Examples
    --------
    >>> import asyncio
    >>> async def demo():
    ...     process = await spawn_async(
    ...         ("tmux", "-V"), stdin=asyncio.subprocess.DEVNULL
    ...     )
    ...     out, _ = await process.communicate()
    ...     return out.startswith(b"tmux ")
    >>> asyncio.run(demo())
    True
    """
    spawn = asyncio.ensure_future(
        asyncio.create_subprocess_exec(
            *cmd,
            stdin=stdin,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        ),
    )
    try:
        return await asyncio.shield(spawn)
    except asyncio.CancelledError:
        # Let the spawn finish so the client it made can be killed and reaped
        # here, rather than abandoned to asyncio.
        await _reap_spawn(spawn)
        raise
    except FileNotFoundError:
        raise exc.TmuxCommandNotFound from None
    except Exception:
        logger.error(  # noqa: TRY400
            "tmux subprocess failed",
            extra={"tmux_cmd": shlex.join(cmd)},
        )
        raise


async def run_argv_async(
    cmd: tuple[str, ...],
    request: CommandRequest,
) -> CommandResult:
    """Run *cmd* as a child process on the event loop and return the result.

    The asyncio counterpart of :func:`run_argv`, and the one place the async
    engines start a tmux client. Cancellation is a first-class outcome: when
    the awaiting task is cancelled, the client and its process group are
    killed and reaped before :exc:`asyncio.CancelledError` propagates, so no
    tmux process outlives the call that started it. The same happens when
    ``request.timeout`` elapses.

    Parameters
    ----------
    cmd : tuple of str
        The full argv, program first.
    request : CommandRequest
        The request, for ``input``, ``timeout`` and log context.

    Returns
    -------
    CommandResult
        Output and exit status; a failure is data. ``process`` is ``None``:
        the client is an asyncio process, not a :class:`subprocess.Popen`.

    Raises
    ------
    :exc:`~libtmux.exc.TmuxCommandNotFound`
        The program in ``cmd[0]`` is missing or not executable.
    :exc:`~libtmux.exc.TmuxTimeout`
        ``request.timeout`` elapsed; the client was killed and reaped.
    :exc:`asyncio.CancelledError`
        The caller was cancelled; the client was killed and reaped first.

    Examples
    --------
    >>> import asyncio
    >>> from libtmux.engines import CommandRequest
    >>> asyncio.run(
    ...     run_argv_async(
    ...         ("tmux", "-V"), CommandRequest.from_args("-V")
    ...     )
    ... ).stdout[0].startswith("tmux ")
    True
    """
    payload: bytes | None
    if request.input is None:
        payload = None
    elif isinstance(request.input, str):
        payload = request.input.encode("utf-8")
    else:
        payload = request.input
    process = await spawn_async(
        cmd,
        stdin=asyncio.subprocess.DEVNULL
        if payload is None
        else asyncio.subprocess.PIPE,
    )

    communicate = asyncio.ensure_future(process.communicate(payload))
    try:
        done, _ = await asyncio.wait({communicate}, timeout=request.timeout)
    except BaseException:
        # Cancelled (or interrupted) while waiting: the client must not
        # outlive this call.
        await _kill_and_reap_async(process, communicate)
        raise
    if not done:
        await _kill_and_reap_async(process, communicate)
        assert request.timeout is not None
        logger.error(
            "tmux command timed out",
            extra={
                "tmux_cmd": shlex.join(cmd),
                "tmux_timeout": request.timeout,
            },
        )
        raise exc.TmuxTimeout(cmd=list(cmd), timeout=request.timeout)
    try:
        raw_out, raw_err = communicate.result()
    except Exception:
        await _kill_and_reap_async(process)
        logger.error(  # noqa: TRY400
            "tmux subprocess failed",
            extra={"tmux_cmd": shlex.join(cmd)},
        )
        raise
    return _build_result(
        cmd,
        request,
        _decode_text(raw_out),
        _decode_text(raw_err),
        process.returncode if process.returncode is not None else -1,
        None,
    )


class SubprocessEngine:
    """Execute tmux commands by forking the tmux CLI binary.

    Parameters
    ----------
    connection : ServerConnection, optional
        The tmux binary and connection flags to dispatch through. Defaults to
        the ambient tmux server on ``$PATH``.

    Examples
    --------
    >>> from libtmux.engines import CommandRequest, SubprocessEngine
    >>> engine = SubprocessEngine.for_server(server)
    >>> engine.run(CommandRequest.from_args("display-message", "-p", "hi")).stdout
    ('hi',)
    """

    def __init__(self, connection: ServerConnection | None = None) -> None:
        self._conn = connection if connection is not None else ServerConnection()

    @classmethod
    def of(
        cls,
        tmux_bin: str | pathlib.Path | None = None,
        server_args: Sequence[str] = (),
    ) -> SubprocessEngine:
        """Build an engine from a binary path and raw connection flags.

        Parameters
        ----------
        tmux_bin : str or pathlib.Path, optional
            Explicit tmux binary; resolved from ``$PATH`` when ``None``.
        server_args : Sequence[str]
            Connection flags, e.g. ``("-Lwork",)``.

        Returns
        -------
        SubprocessEngine
            The engine.

        Examples
        --------
        >>> SubprocessEngine.of(server_args=["-Lwork"]).server_args
        ('-Lwork',)
        """
        return cls(ServerConnection.of(tmux_bin, server_args))

    def with_connection(self, connection: ServerConnection) -> SubprocessEngine:
        """Return an equivalent engine dispatching over *connection*.

        Engines are immutable with respect to their connection, so this returns
        a new engine rather than rebinding this one.
        :attr:`Server.engine <libtmux.Server.engine>` calls it to bind an engine
        that names no server of its own.

        Parameters
        ----------
        connection : ServerConnection
            The connection the returned engine dispatches over.

        Returns
        -------
        SubprocessEngine
            A new engine; this one is left untouched.

        Examples
        --------
        >>> from libtmux.engines import ServerConnection
        >>> engine = SubprocessEngine()
        >>> engine.server_args
        ()
        >>> engine.with_connection(ServerConnection.of(args=("-Lwork",))).server_args
        ('-Lwork',)
        >>> engine.server_args
        ()
        """
        return type(self)(connection)

    @classmethod
    def for_server(cls, server: t.Any) -> SubprocessEngine:
        """Build an engine bound to a live :class:`libtmux.Server`'s socket.

        Parameters
        ----------
        server : typing.Any
            Any object shaped like a :class:`libtmux.Server`.

        Returns
        -------
        SubprocessEngine
            An engine reaching the same tmux server as the object API.

        Examples
        --------
        >>> SubprocessEngine.for_server(server).server_args[0].startswith("-L")
        True
        """
        return cls(ServerConnection.from_server(server))

    @property
    def connection(self) -> ServerConnection:
        """The tmux binary + connection flags this engine dispatches through.

        Returns
        -------
        ServerConnection
            The connection.

        Examples
        --------
        >>> SubprocessEngine.of("tmux").connection.tmux_bin
        'tmux'
        """
        return self._conn

    @property
    def tmux_bin(self) -> str | None:
        """The explicitly configured tmux binary, if any.

        Returns
        -------
        str or None
            The declared binary; ``None`` when resolved from ``$PATH``.

        Examples
        --------
        >>> SubprocessEngine.of("/usr/bin/tmux").tmux_bin
        '/usr/bin/tmux'
        """
        return self._conn.tmux_bin

    @property
    def server_args(self) -> tuple[str, ...]:
        """Connection flags placed before every tmux subcommand.

        Returns
        -------
        tuple[str, ...]
            The flags.

        Examples
        --------
        >>> SubprocessEngine.of(server_args=("-Ltest",)).server_args
        ('-Ltest',)
        """
        return self._conn.args

    def tmux_version(self) -> str | None:
        """Report the tmux version this engine dispatches to (memoized).

        Satisfies :class:`~libtmux.engines.base.SupportsTmuxVersion`.

        Returns
        -------
        str or None
            The version, or ``None`` when the binary is missing or unparseable.

        Examples
        --------
        >>> SubprocessEngine.for_server(server).tmux_version() is not None
        True
        """
        return self._conn.tmux_version()

    def command_line(self, request: CommandRequest) -> tuple[str, ...]:
        r"""Return the full argv *request* would run as, without running it.

        Parameters
        ----------
        request : CommandRequest
            The command.

        Returns
        -------
        tuple[str, ...]
            Binary, connection flags, then the encoded command argv.

        Examples
        --------
        >>> from libtmux.engines import CommandRequest
        >>> SubprocessEngine.of("tmux", ("-Lwork",)).command_line(
        ...     CommandRequest.from_args("send-keys", "echo hi")
        ... )
        ('tmux', '-Lwork', 'send-keys', 'echo hi')
        """
        return self._conn.argv(*request.args, tmux_bin=request.tmux_bin)

    def run(self, request: CommandRequest) -> CommandResult:
        """Execute one tmux command via :mod:`subprocess` and return its result.

        Parameters
        ----------
        request : CommandRequest
            The command.

        Returns
        -------
        CommandResult
            Structured output, carrying the :class:`subprocess.Popen` that ran.

        Raises
        ------
        :exc:`~libtmux.exc.TmuxCommandNotFound`
            The tmux binary is missing or not executable.

        Examples
        --------
        >>> from libtmux.engines import CommandRequest
        >>> engine = SubprocessEngine.for_server(server)
        >>> engine.run(CommandRequest.from_args("has-session", "-t", "nope")).returncode
        1
        """
        return run_argv(self.command_line(request), request)

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Execute each request in order, one fork per command.

        Parameters
        ----------
        requests : Sequence[CommandRequest]
            Commands to run.

        Returns
        -------
        list[CommandResult]
            One result per request, in order.

        Examples
        --------
        >>> from libtmux.engines import CommandRequest
        >>> results = SubprocessEngine.for_server(server).run_batch(
        ...     [
        ...         CommandRequest.from_args("display-message", "-p", "one"),
        ...         CommandRequest.from_args("display-message", "-p", "two"),
        ...     ]
        ... )
        >>> [result.stdout[0] for result in results]
        ['one', 'two']
        """
        return [self.run(request) for request in requests]


class AsyncSubprocessEngine:
    """Execute tmux commands by running the tmux CLI on the event loop.

    The awaitable counterpart of :class:`SubprocessEngine`, and the base of the
    asyncio API. Each command is one tmux client started in its own session
    and process group. Cancelling the awaiting task, or a request's
    ``timeout`` elapsing, kills the client and its group and reaps it before
    the call returns, so nothing the call started outlives it.

    ``asyncio.to_thread`` around a blocking call cannot give that guarantee:
    cancelling it abandons the thread and leaves the tmux client running.

    Parameters
    ----------
    connection : ServerConnection, optional
        The tmux binary and connection flags to dispatch through. Defaults to
        the ambient tmux server on ``$PATH``.

    Notes
    -----
    A client running while the engine closes is killed and reaped by
    :meth:`aclose`, and a closed engine raises
    :exc:`~libtmux.exc.EngineClosed` instead of starting another.

    Examples
    --------
    >>> import asyncio
    >>> from libtmux.engines import AsyncSubprocessEngine, CommandRequest
    >>> async def demo():
    ...     async with AsyncSubprocessEngine.for_server(server) as engine:
    ...         result = await engine.run(
    ...             CommandRequest.from_args("display-message", "-p", "hi")
    ...         )
    ...         return result.stdout
    >>> asyncio.run(demo())
    ('hi',)
    """

    def __init__(self, connection: ServerConnection | None = None) -> None:
        self._conn = connection if connection is not None else ServerConnection()
        self._closed = False
        self._version: str | None = None
        self._version_probed = False

    @classmethod
    def of(
        cls,
        tmux_bin: str | pathlib.Path | None = None,
        server_args: Sequence[str] = (),
    ) -> AsyncSubprocessEngine:
        """Build an engine from a binary path and raw connection flags.

        Examples
        --------
        >>> AsyncSubprocessEngine.of(server_args=["-Lwork"]).server_args
        ('-Lwork',)
        """
        return cls(ServerConnection.of(tmux_bin, server_args))

    @classmethod
    def for_server(cls, server: t.Any) -> AsyncSubprocessEngine:
        """Build an engine bound to a live :class:`libtmux.Server`'s socket.

        Examples
        --------
        >>> AsyncSubprocessEngine.for_server(server).server_args[0].startswith("-L")
        True
        """
        return cls(ServerConnection.from_server(server))

    def with_connection(self, connection: ServerConnection) -> AsyncSubprocessEngine:
        """Return an equivalent engine dispatching over *connection*.

        Examples
        --------
        >>> from libtmux.engines import ServerConnection
        >>> AsyncSubprocessEngine().with_connection(
        ...     ServerConnection.of(args=("-Lwork",))
        ... ).server_args
        ('-Lwork',)
        """
        return type(self)(connection)

    @property
    def connection(self) -> ServerConnection:
        """The tmux binary and connection flags this engine dispatches through."""
        return self._conn

    @property
    def tmux_bin(self) -> str | None:
        """The explicitly configured tmux binary, if any."""
        return self._conn.tmux_bin

    @property
    def server_args(self) -> tuple[str, ...]:
        """Connection flags placed before every tmux subcommand."""
        return self._conn.args

    def command_line(self, request: CommandRequest) -> tuple[str, ...]:
        """Return the full argv *request* would run as, without running it.

        Examples
        --------
        >>> from libtmux.engines import CommandRequest
        >>> AsyncSubprocessEngine.of("tmux", ("-Lwork",)).command_line(
        ...     CommandRequest.from_args("list-panes")
        ... )
        ('tmux', '-Lwork', 'list-panes')
        """
        return self._conn.argv(*request.args, tmux_bin=request.tmux_bin)

    async def tmux_version(self) -> str | None:
        """Report the tmux version this engine dispatches to, probing once.

        The awaitable twin of :meth:`SubprocessEngine.tmux_version`: the probe
        runs on the loop, so it neither blocks it nor escapes cancellation.

        Returns
        -------
        str or None
            The version, or ``None`` when the binary is missing or its output
            cannot be read.

        Examples
        --------
        >>> import asyncio
        >>> asyncio.run(AsyncSubprocessEngine().tmux_version()) is not None
        True
        """
        if not self._version_probed:
            try:
                result = await run_argv_async(
                    (self._conn.resolve_bin(), "-V"),
                    CommandRequest(args=("-V",), timeout=30),
                )
            except (exc.LibTmuxException, exc.TmuxTimeout, OSError):
                return None
            self._version_probed = True
            if result.ok and result.stdout:
                self._version = result.stdout[0].removeprefix("tmux ").strip()
        return self._version

    async def run(self, request: CommandRequest) -> CommandResult:
        """Execute one tmux command and return its result.

        Parameters
        ----------
        request : CommandRequest
            The command.

        Returns
        -------
        CommandResult
            Structured output; a tmux-side failure is data.

        Raises
        ------
        :exc:`~libtmux.exc.EngineClosed`
            The engine was closed.
        :exc:`~libtmux.exc.TmuxCommandNotFound`
            The tmux binary is missing or not executable.
        :exc:`~libtmux.exc.TmuxTimeout`
            ``request.timeout`` elapsed; the client was killed and reaped.
        :exc:`asyncio.CancelledError`
            The caller was cancelled; the client was killed and reaped first.

        Examples
        --------
        >>> import asyncio
        >>> from libtmux.engines import CommandRequest
        >>> engine = AsyncSubprocessEngine.for_server(server)
        >>> asyncio.run(
        ...     engine.run(CommandRequest.from_args("has-session", "-t", "nope"))
        ... ).returncode
        1
        """
        self._raise_if_closed()
        return await run_argv_async(self.command_line(request), request)

    async def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Execute each request in order, one client per command.

        Requests run one after another, never together, because tmux commands
        in a batch are ordered. Cancelling the batch cancels the command in
        flight and starts no later one.

        Examples
        --------
        >>> import asyncio
        >>> from libtmux.engines import CommandRequest
        >>> engine = AsyncSubprocessEngine.for_server(server)
        >>> results = asyncio.run(
        ...     engine.run_batch(
        ...         [
        ...             CommandRequest.from_args("display-message", "-p", "one"),
        ...             CommandRequest.from_args("display-message", "-p", "two"),
        ...         ]
        ...     )
        ... )
        >>> [result.stdout[0] for result in results]
        ['one', 'two']
        """
        return [await self.run(request) for request in requests]

    async def aclose(self) -> None:
        """Close the engine. Safe to call twice.

        A client that is still running belongs to a task that is still
        awaiting it, and that task kills and reaps it when it is cancelled;
        closing only stops the engine accepting new commands.
        """
        self._closed = True

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

    def _raise_if_closed(self) -> None:
        if self._closed:
            msg = "the async subprocess engine is closed"
            raise exc.EngineClosed(msg)
