"""Pluggable raw-byte command execution transports for tmux."""

from __future__ import annotations

import contextlib
import logging
import os
import pathlib
import selectors
import shlex
import subprocess
import threading
import time
import typing as t
from dataclasses import dataclass, field

from libtmux import exc
from libtmux._internal.connection import ServerConnection
from libtmux._internal.control_mode import (
    ControlFrame,
    ControlModeParser,
    ControlNotification,
    render_control_command,
)
from libtmux._internal.daemon_guard import (
    DaemonGuard,
    is_daemon_guard_refusal,
    wrap_daemon_guard,
)
from libtmux._internal.invocation import (
    flatten_commands,
    split_command_chain,
    split_direct_argv,
)
from libtmux._internal.protocols import ClientProcess

__all__ = (
    "AsyncTmuxEngine",
    "ControlModeEngine",
    "DaemonGuard",
    "ExecEngine",
    "SubprocessEngine",
    "TmuxEngine",
    "TmuxRequest",
    "TmuxResult",
)

logger = logging.getLogger(__name__)

# Subcommands that wait asynchronously, stream files, detach/kill the server,
# or require a non-control client TTY. ControlModeEngine routes these through
# SubprocessEngine so control-mode framing cannot deadlock or EBADF.
_SUBPROCESS_ONLY_SUBCOMMANDS: t.Final[frozenset[str]] = frozenset(
    {
        "attach",
        "attach-session",
        "capture-pane",
        "capturep",
        "detach",
        "detach-client",
        "display-popup",
        "popup",
        "kill-server",
        "load-buffer",
        "loadb",
        "new-pane",
        "newp",
        "run",
        "run-shell",
        "save-buffer",
        "saveb",
        "show-buffer",
        "showb",
        "source",
        "source-file",
        "start",
        "start-server",
        "suspend-client",
        "suspendc",
        "wait",
        "wait-for",
    }
)


@dataclass(frozen=True, slots=True)
class TmuxRequest:
    """Transport-neutral tmux invocation request.

    Attributes
    ----------
    commands : tuple[tuple[str, ...], ...]
        Ordered tmux commands to execute in one invocation group. Empty only
        when client-level flags such as ``("-V",)`` are supplied in
        ``client_args``.
    client_args : tuple[str, ...]
        Per-invocation tmux client flags (such as ``"-u"``, ``"-N"``, ``"-v"``,
        ``"-D"``, ``"-f"``) placed before the first subcommand.
    stdin : bytes or None
        Raw standard-input payload for commands reading ``"-"``.
    timeout : float or None
        Wall-clock deadline in seconds; ``None`` leaves blocking commands
        unbounded.
    env : typing.Mapping[str, str] or None
        Environment variables for this invocation.
    inherit_env : bool
        When ``True`` (default), ``env`` overlays :data:`os.environ`; when
        ``False``, ``env`` replaces the process environment completely.
    cwd : pathlib.Path or None
        Working directory for the client process.
    daemon_guard : DaemonGuard or None
        Optional ``#{pid}`` and ``#{start_time}`` generation fence.
    tmux_bin : str or None
        Optional per-request executable override.

    Examples
    --------
    >>> from libtmux.engine import TmuxRequest
    >>> req = TmuxRequest.from_args("list-sessions", "-F#S")
    >>> req.commands
    (('list-sessions', '-F#S'),)
    >>> req.subcommand
    'list-sessions'
    """

    commands: tuple[tuple[str, ...], ...]
    client_args: tuple[str, ...] = ()
    stdin: bytes | None = None
    timeout: float | None = None
    env: t.Mapping[str, str] | None = None
    inherit_env: bool = True
    cwd: pathlib.Path | None = None
    daemon_guard: DaemonGuard | None = None
    tmux_bin: str | None = None

    def __post_init__(self) -> None:
        """Normalize and validate command and client tokens."""
        norm_client = tuple(str(arg) for arg in self.client_args)
        norm_cmds = tuple(tuple(str(token) for token in cmd) for cmd in self.commands)
        if any("\x00" in arg for arg in norm_client) or any(
            "\x00" in tok for cmd in norm_cmds for tok in cmd
        ):
            msg = "tmux command arguments cannot contain NUL"
            raise ValueError(msg)
        if any(not cmd for cmd in norm_cmds):
            msg = "tmux command tuple cannot be empty"
            raise ValueError(msg)
        if not norm_cmds and not norm_client:
            msg = "TmuxRequest requires at least one command or client flag"
            raise ValueError(msg)
        if self.cwd is not None and not isinstance(self.cwd, pathlib.Path):
            object.__setattr__(self, "cwd", pathlib.Path(self.cwd))
        object.__setattr__(self, "client_args", norm_client)
        object.__setattr__(self, "commands", norm_cmds)

    @classmethod
    def from_args(
        cls,
        *args: object,
        client_args: t.Sequence[str] = (),
        stdin: bytes | None = None,
        timeout: float | None = None,
        env: t.Mapping[str, str] | None = None,
        inherit_env: bool = True,
        cwd: pathlib.Path | str | None = None,
        daemon_guard: DaemonGuard | None = None,
        tmux_bin: str | pathlib.Path | None = None,
    ) -> TmuxRequest:
        """Build a request from positional CLI tokens.

        Leading client-level flags (for example ``"-Lwork"`` or ``"-V"``) are
        split into ``client_args`` automatically so callers may pass raw CLI
        vectors or pure subcommand tokens.

        Examples
        --------
        >>> from libtmux.engine import TmuxRequest
        >>> req = TmuxRequest.from_args("-Lwork", "list-panes", "-a")
        >>> req.client_args, req.commands
        (('-Lwork',), (('list-panes', '-a'),))
        """
        split = split_direct_argv(args)
        merged_client = (*client_args, *split.client_args)
        commands = split_command_chain(split.command_args)
        return cls(
            commands=commands,
            client_args=merged_client,
            stdin=stdin,
            timeout=timeout,
            env=env,
            inherit_env=inherit_env,
            cwd=pathlib.Path(cwd) if cwd is not None else None,
            daemon_guard=daemon_guard,
            tmux_bin=str(tmux_bin) if tmux_bin is not None else None,
        )

    @property
    def subcommand(self) -> str:
        """First subcommand name, or ``""`` for client-flag-only requests."""
        return self.commands[0][0] if self.commands and self.commands[0] else ""


@dataclass(frozen=True, slots=True)
class TmuxResult:
    r"""Lossless raw-byte outcome of executing a :class:`TmuxRequest`.

    Attributes
    ----------
    argv : tuple[str, ...]
        Full command vector dispatched by the engine.
    stdout : bytes
        Raw standard-output bytes, unmodified.
    stderr : bytes
        Raw standard-error bytes, unmodified.
    returncode : int
        Exit status reported by tmux (``0`` on success).
    _process : subprocess.Popen[bytes] or None
        Underlying child process when dispatched by a subprocess engine;
        excluded from equality, hashing, and :func:`repr`.

    Examples
    --------
    >>> from libtmux.engine import TmuxResult
    >>> res = TmuxResult(argv=("tmux", "list-sessions"), stdout=b"$0\n")
    >>> res.stdout, res.returncode
    (b'$0\n', 0)
    """

    argv: tuple[str, ...]
    stdout: bytes = b""
    stderr: bytes = b""
    returncode: int = 0
    _process: subprocess.Popen[bytes] | None = field(
        default=None,
        repr=False,
        compare=False,
        hash=False,
    )


@t.runtime_checkable
class TmuxEngine(t.Protocol):
    r"""Synchronous tmux command transport protocol.

    Examples
    --------
    >>> from libtmux.engine import TmuxEngine, TmuxRequest, TmuxResult
    >>> class EchoEngine:
    ...     endpoint = None
    ...     def execute(self, request: TmuxRequest) -> TmuxResult:
    ...         return TmuxResult(argv=("tmux", *request.commands[0]), stdout=b"ok\n")
    >>> isinstance(EchoEngine(), TmuxEngine)
    True
    """

    @property
    def endpoint(self) -> str | None:
        """Transport endpoint identifier (``None`` for local host)."""
        ...

    def execute(self, request: TmuxRequest) -> TmuxResult:
        """Execute *request* synchronously and return its raw byte result."""
        ...


@t.runtime_checkable
class AsyncTmuxEngine(t.Protocol):
    """Asynchronous tmux command transport protocol."""

    @property
    def endpoint(self) -> str | None:
        """Transport endpoint identifier (``None`` for local host)."""
        ...

    async def execute(self, request: TmuxRequest) -> TmuxResult:
        """Execute *request* asynchronously and return its raw byte result."""
        ...


def _build_process_env(request: TmuxRequest) -> dict[str, str] | None:
    if not request.inherit_env:
        return dict(request.env) if request.env is not None else {}
    if request.env is not None:
        return {**os.environ, **request.env}
    return None


def _prepare_argv_and_guard(
    connection: ServerConnection,
    request: TmuxRequest,
) -> tuple[tuple[str, ...], str | None]:
    commands = request.commands
    guard_marker: str | None = None
    if request.daemon_guard is not None:
        commands, guard_marker = wrap_daemon_guard(commands, request.daemon_guard)
    flat_commands = flatten_commands(commands, check_imsg_limits=True)
    argv = connection.argv(
        *request.client_args,
        *flat_commands,
        tmux_bin=request.tmux_bin,
    )
    return argv, guard_marker


def _run_popen_request(
    argv: tuple[str, ...],
    request: TmuxRequest,
    guard_marker: str | None,
) -> TmuxResult:
    proc_env = _build_process_env(request)
    stdin_mode = subprocess.PIPE if request.stdin is not None else subprocess.DEVNULL
    try:
        process = subprocess.Popen(
            argv,
            stdin=stdin_mode,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=proc_env,
            cwd=request.cwd,
        )
    except FileNotFoundError:
        raise exc.TmuxCommandNotFound from None
    except Exception:
        logger.error(  # noqa: TRY400
            "tmux subprocess failed",
            extra={"tmux_cmd": shlex.join(argv)},
        )
        raise

    try:
        stdout_bytes, stderr_bytes = process.communicate(
            input=request.stdin,
            timeout=request.timeout,
        )
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        assert request.timeout is not None
        raise exc.TmuxCommandTimeout(argv, request.timeout) from None

    returncode = process.returncode
    if (
        guard_marker is not None
        and request.daemon_guard is not None
        and is_daemon_guard_refusal(stderr_bytes, guard_marker)
    ):
        raise exc.TmuxServerRestarted(
            request.daemon_guard.pid,
            request.daemon_guard.start_time,
        )

    result = TmuxResult(
        argv=argv,
        stdout=stdout_bytes,
        stderr=stderr_bytes,
        returncode=returncode,
        _process=process,
    )
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "tmux subprocess completed",
            extra={
                "tmux_cmd": shlex.join(argv),
                "tmux_subcommand": request.subcommand,
                "tmux_exit_code": returncode,
                "tmux_stdout_len": len(stdout_bytes),
                "tmux_stderr_len": len(stderr_bytes),
            },
        )
    return result


class SubprocessEngine:
    r"""Default engine executing one ``tmux`` CLI process per request.

    Parameters
    ----------
    connection : ServerConnection, optional
        Binary and server flags to dispatch through.

    Examples
    --------
    >>> from libtmux.engine import SubprocessEngine, TmuxRequest
    >>> engine = SubprocessEngine.for_server(server)
    >>> engine.execute(TmuxRequest.from_args("display-message", "-p", "hi")).stdout
    b'hi\n'
    """

    def __init__(self, connection: ServerConnection | None = None) -> None:
        self._conn = connection if connection is not None else ServerConnection()

    @property
    def endpoint(self) -> None:
        """Local host endpoint (always ``None``)."""
        return None

    @classmethod
    def of(
        cls,
        tmux_bin: str | pathlib.Path | None = None,
        server_args: t.Sequence[str] = (),
    ) -> SubprocessEngine:
        """Build an engine from an explicit binary path and server flags."""
        return cls(ServerConnection.of(tmux_bin, server_args))

    @classmethod
    def for_server(cls, server: t.Any) -> SubprocessEngine:
        """Build an engine targeting *server*'s configured socket and flags."""
        return cls(ServerConnection.from_server(server))

    def with_connection(self, connection: ServerConnection) -> SubprocessEngine:
        """Return a new engine dispatching over *connection*."""
        return type(self)(connection)

    @property
    def connection(self) -> ServerConnection:
        """Underlying :class:`~libtmux._internal.connection.ServerConnection`."""
        return self._conn

    @property
    def tmux_bin(self) -> str | None:
        """Declared tmux executable, or ``None`` when resolved from ``$PATH``."""
        return self._conn.tmux_bin

    @property
    def server_args(self) -> tuple[str, ...]:
        """Server-selecting flags placed before every subcommand."""
        return self._conn.args

    def tmux_version(self) -> str | None:
        """Return the memoized tmux version string, or ``None``."""
        return self._conn.tmux_version()

    def command_line(self, request: TmuxRequest) -> tuple[str, ...]:
        """Render the full argv *request* would execute."""
        argv, _marker = _prepare_argv_and_guard(self._conn, request)
        return argv

    def execute(self, request: TmuxRequest) -> TmuxResult:
        """Execute *request* via :class:`subprocess.Popen` in binary mode."""
        argv, guard_marker = _prepare_argv_and_guard(self._conn, request)
        return _run_popen_request(argv, request, guard_marker)

    def execute_batch(self, requests: t.Sequence[TmuxRequest]) -> list[TmuxResult]:
        """Execute *requests* sequentially, one process per request."""
        return [self.execute(req) for req in requests]

    def spawn_client(self, request: TmuxRequest) -> ClientProcess:
        """Spawn *request* without waiting for completion."""
        argv, _marker = _prepare_argv_and_guard(self._conn, request)
        proc_env = _build_process_env(request)
        try:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=proc_env,
                cwd=request.cwd,
            )
        except FileNotFoundError:
            raise exc.TmuxCommandNotFound from None
        if request.stdin is not None and process.stdin is not None:
            process.stdin.write(request.stdin)
            process.stdin.close()
        return ClientProcess(argv=argv, process=process)


class ExecEngine:
    """Execute ``tmux`` inside an external command prefix (``docker exec``, ``ssh``).

    Parameters
    ----------
    prefix : typing.Sequence[str]
        Leading command tokens prepended before the ``tmux`` executable (for
        example ``("docker", "exec", "-i", "my-container")``).
    connection : ServerConnection, optional
        Remote ``tmux`` executable name (defaults to ``"tmux"``) and server
        flags.
    endpoint : str, optional
        Explicit endpoint label; defaults to ``"exec:<prefix>"``.

    Examples
    --------
    >>> from libtmux.engine import ExecEngine, TmuxRequest
    >>> engine = ExecEngine(("docker", "exec", "-i", "app"))
    >>> engine.endpoint
    'exec:docker exec -i app'
    >>> engine.command_line(TmuxRequest.from_args("list-sessions"))
    ('docker', 'exec', '-i', 'app', 'tmux', 'list-sessions')
    """

    def __init__(
        self,
        prefix: t.Sequence[str],
        connection: ServerConnection | None = None,
        *,
        endpoint: str | None = None,
    ) -> None:
        if not prefix:
            msg = "ExecEngine requires a non-empty command prefix"
            raise ValueError(msg)
        self._prefix = tuple(str(part) for part in prefix)
        if any("\x00" in part for part in self._prefix):
            msg = "ExecEngine prefix cannot contain NUL"
            raise ValueError(msg)
        base_conn = (
            connection if connection is not None else ServerConnection(tmux_bin="tmux")
        )
        if base_conn.tmux_bin is None:
            base_conn = ServerConnection.of(tmux_bin="tmux", args=base_conn.args)
        self._conn = base_conn
        self._endpoint = endpoint or f"exec:{shlex.join(self._prefix)}"

    @property
    def endpoint(self) -> str:
        """Distinct endpoint label identifying the wrapper target."""
        return self._endpoint

    @property
    def prefix(self) -> tuple[str, ...]:
        """Wrapper command prefix."""
        return self._prefix

    @property
    def connection(self) -> ServerConnection:
        """Remote tmux binary and server flags."""
        return self._conn

    def with_connection(self, connection: ServerConnection) -> ExecEngine:
        """Return a copy targeting *connection* over the same wrapper prefix."""
        target = (
            connection
            if connection.tmux_bin is not None
            else ServerConnection.of(tmux_bin="tmux", args=connection.args)
        )
        return ExecEngine(self._prefix, target, endpoint=self._endpoint)

    def command_line(self, request: TmuxRequest) -> tuple[str, ...]:
        """Render wrapper prefix followed by remote ``tmux`` argv."""
        tmux_argv, _marker = _prepare_argv_and_guard(self._conn, request)
        return (*self._prefix, *tmux_argv)

    def execute(self, request: TmuxRequest) -> TmuxResult:
        """Execute *request* through the wrapper prefix."""
        tmux_argv, guard_marker = _prepare_argv_and_guard(self._conn, request)
        full_argv = (*self._prefix, *tmux_argv)
        return _run_popen_request(full_argv, request, guard_marker)

    def execute_batch(self, requests: t.Sequence[TmuxRequest]) -> list[TmuxResult]:
        """Execute *requests* sequentially through the wrapper prefix."""
        return [self.execute(req) for req in requests]

    def spawn_client(self, request: TmuxRequest) -> ClientProcess:
        """Spawn a non-blocking wrapper client process."""
        full_argv = self.command_line(request)
        proc_env = _build_process_env(request)
        try:
            process = subprocess.Popen(
                full_argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=proc_env,
                cwd=request.cwd,
            )
        except FileNotFoundError:
            raise exc.TmuxCommandNotFound from None
        if request.stdin is not None and process.stdin is not None:
            process.stdin.write(request.stdin)
            process.stdin.close()
        return ClientProcess(argv=full_argv, process=process)


class ControlModeEngine:
    """Persistent ``tmux -u -C`` pipelining engine for ``tmux >= 3.7``.

    Single non-blocking commands without ``stdin`` or per-call process
    overrides pipeline over one persistent control client, matching only
    ``flags == 1`` ``%begin``/``%end``/``%error`` blocks so unsolicited
    ``flags == 0`` ``after-*`` hook output cannot corrupt replies. Requests
    requiring binary ``stdin``, blocking waits, client flags, or multi-command
    groups automatically fall back to :class:`SubprocessEngine` on the same
    connection.

    Parameters
    ----------
    connection : ServerConnection, optional
        Binary and server flags to dispatch through.
    default_timeout : float
        Default timeout in seconds for control-mode replies.
    """

    def __init__(
        self,
        connection: ServerConnection | None = None,
        *,
        default_timeout: float = 10.0,
    ) -> None:
        self._conn = connection if connection is not None else ServerConnection()
        self._fallback = SubprocessEngine(self._conn)
        self._default_timeout = default_timeout
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[bytes] | None = None
        self._selector: selectors.BaseSelector | None = None
        self._parser = ControlModeParser()
        self._version_checked = False
        self.unsolicited_frames: list[ControlFrame] = []
        self.notifications: list[object] = []

    @property
    def endpoint(self) -> None:
        """Local host endpoint (always ``None``)."""
        return None

    @classmethod
    def for_server(
        cls,
        server: t.Any,
        *,
        default_timeout: float = 10.0,
    ) -> ControlModeEngine:
        """Build a control-mode engine targeting *server*'s socket."""
        return cls(
            ServerConnection.from_server(server),
            default_timeout=default_timeout,
        )

    @property
    def connection(self) -> ServerConnection:
        """Underlying :class:`~libtmux._internal.connection.ServerConnection`."""
        return self._conn

    def with_connection(self, connection: ServerConnection) -> ControlModeEngine:
        """Return a fresh engine targeting *connection*."""
        return ControlModeEngine(
            connection,
            default_timeout=self._default_timeout,
        )

    def tmux_version(self) -> str | None:
        """Return the memoized tmux version string, or ``None``."""
        return self._conn.tmux_version()

    def command_line(self, request: TmuxRequest) -> tuple[str, ...]:
        """Render the logical argv *request* represents."""
        return self._fallback.command_line(request)

    def _can_use_control_mode(self, request: TmuxRequest) -> bool:
        if (
            request.stdin is not None
            or request.env is not None
            or not request.inherit_env
            or request.cwd is not None
            or request.daemon_guard is not None
            or request.tmux_bin is not None
            or len(request.commands) != 1
        ):
            return False
        if any(flag != "-u" for flag in request.client_args):
            return False
        subcmd = request.subcommand
        return bool(subcmd) and subcmd not in _SUBPROCESS_ONLY_SUBCOMMANDS

    def _ensure_version_supported(self) -> None:
        if self._version_checked:
            return
        from libtmux._internal.support.capabilities import (
            capability_since,
            probe_daemon_identity,
            supports_interval,
        )

        min_ver = capability_since("control-mode")
        identity = probe_daemon_identity(self._fallback)
        version = (
            identity.version if identity is not None else self._conn.tmux_version()
        )
        if version is not None and not supports_interval(version, since=min_ver):
            msg = (
                f"ControlModeEngine requires connected tmux {min_ver} or newer "
                f"(observed {version})"
            )
            raise exc.VersionTooLow(msg)
        self._version_checked = True

    def _ensure_connected_locked(self, timeout: float) -> subprocess.Popen[bytes]:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        self._close_locked()
        self._ensure_version_supported()

        # Check that the server is reachable before spawning `-u -C` without a
        # subcommand (which creates an unattached control client on a live server,
        # or exits immediately if no server/sessions exist unless kept alive).
        probe = self._fallback.execute(
            TmuxRequest(
                commands=(("list-sessions", "-F", "#{session_id}"),),
                client_args=("-u",),
            )
        )
        if probe.returncode != 0 or not probe.stdout.strip():
            msg = (
                probe.stderr.decode("utf-8", errors="replace").strip()
                or "no live session to attach control client"
            )
            raise exc.TmuxTransportError(msg)
        first_session = (
            probe.stdout.splitlines()[0].decode("ascii", errors="replace").strip()
        )

        argv = self._conn.argv("-u", "-C", "attach-session", "-t", first_session)
        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            raise exc.TmuxCommandNotFound from None

        sel = selectors.DefaultSelector()
        assert proc.stdout is not None
        sel.register(proc.stdout, selectors.EVENT_READ)
        self._proc = proc
        self._selector = sel
        self._parser = ControlModeParser()

        # Drain the initial attach %begin ... 0 / %end ... 0 frame with a ping.
        frames = self._send_and_collect_locked(
            [render_control_command((("display-message", "-p", ""),))],
            timeout=timeout,
        )
        if len(frames) != 1:
            self._close_locked()
            msg = "failed to synchronize control-mode session"
            raise exc.TmuxTransportError(msg)
        return proc

    def _send_and_collect_locked(
        self,
        wire_lines: list[bytes],
        *,
        timeout: float,
    ) -> list[ControlFrame]:
        assert self._proc is not None
        assert self._proc.stdin is not None
        assert self._selector is not None

        payload = b"".join(wire_lines)
        try:
            self._proc.stdin.write(payload)
            self._proc.stdin.flush()
        except BrokenPipeError as err:
            self._close_locked()
            msg = "tmux control-mode stdin pipe closed unexpectedly"
            raise exc.TmuxTransportError(msg) from err

        replies: list[ControlFrame] = []
        deadline = time.monotonic() + timeout
        expected = len(wire_lines)

        while len(replies) < expected:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._close_locked()
                raise exc.TmuxCommandTimeout(self._conn.argv("-u", "-C"), timeout)
            events = self._selector.select(remaining)
            if not events:
                continue
            for key, _ in events:
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    self._close_locked()
                    msg = "tmux control-mode client exited before completing replies"
                    raise exc.TmuxTransportError(msg)
                for ev in self._parser.feed(chunk):
                    if isinstance(ev, ControlFrame):
                        if ev.is_command_reply:
                            replies.append(ev)
                        else:
                            self.unsolicited_frames.append(ev)
                    elif isinstance(ev, ControlNotification) and ev.kind == "exit":
                        self.notifications.append(ev)
                    else:
                        self.notifications.append(ev)
        return replies

    @staticmethod
    def _frame_to_result(argv: tuple[str, ...], frame: ControlFrame) -> TmuxResult:
        if frame.ok:
            return TmuxResult(
                argv=argv,
                stdout=frame.payload,
                stderr=b"",
                returncode=0,
            )
        return TmuxResult(
            argv=argv,
            stdout=b"",
            stderr=frame.payload,
            returncode=1,
        )

    def execute(self, request: TmuxRequest) -> TmuxResult:
        """Execute *request*, pipelining over ``tmux -u -C`` when eligible."""
        if not self._can_use_control_mode(request):
            return self._fallback.execute(request)

        argv = self._fallback.command_line(request)
        wire = render_control_command(request.commands)
        timeout = (
            request.timeout if request.timeout is not None else self._default_timeout
        )

        with self._lock:
            try:
                self._ensure_connected_locked(timeout=timeout)
                frames = self._send_and_collect_locked([wire], timeout=timeout)
            except exc.TmuxTransportError:
                return self._fallback.execute(request)
        return self._frame_to_result(argv, frames[0])

    def execute_batch(self, requests: t.Sequence[TmuxRequest]) -> list[TmuxResult]:
        """Execute *requests* in order, pipelining contiguous control-eligible runs."""
        if not requests:
            return []
        if not all(self._can_use_control_mode(req) for req in requests):
            results: list[TmuxResult] = []
            run_reqs: list[TmuxRequest] = []

            def flush_run() -> None:
                if not run_reqs:
                    return
                results.extend(self._execute_control_batch(run_reqs))
                run_reqs.clear()

            for req in requests:
                if self._can_use_control_mode(req):
                    run_reqs.append(req)
                else:
                    flush_run()
                    results.append(self._fallback.execute(req))
            flush_run()
            return results
        return self._execute_control_batch(requests)

    def _execute_control_batch(
        self,
        requests: t.Sequence[TmuxRequest],
    ) -> list[TmuxResult]:
        wire_lines = [render_control_command(req.commands) for req in requests]
        argvs = [self._fallback.command_line(req) for req in requests]
        timeouts = [req.timeout for req in requests if req.timeout is not None]
        timeout = min(timeouts) if timeouts else self._default_timeout

        with self._lock:
            try:
                self._ensure_connected_locked(timeout=timeout)
                frames = self._send_and_collect_locked(wire_lines, timeout=timeout)
            except exc.TmuxTransportError:
                return [self._fallback.execute(req) for req in requests]
        return [
            self._frame_to_result(argv, frame)
            for argv, frame in zip(argvs, frames, strict=True)
        ]

    def close(self) -> None:
        """Detach and reap the persistent ``tmux -u -C`` client if active."""
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        if self._selector is not None:
            with contextlib.suppress(Exception):
                self._selector.close()
            self._selector = None
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        if proc.stdin is not None:
            with contextlib.suppress(OSError):
                # Empty newline detaches tmux -C cleanly.
                proc.stdin.write(b"\n")
                proc.stdin.flush()
                proc.stdin.close()
        if proc.poll() is None:
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None:
                with contextlib.suppress(OSError):
                    pipe.close()

    def __enter__(self) -> t.Self:
        """Enter context manager."""
        return self

    def __exit__(self, *_: object) -> None:
        """Close the persistent control client on context exit."""
        self.close()
