"""Asynchronous tmux server and subprocess transport over :mod:`libtmux.engine`."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import pathlib
import shlex
import subprocess
import typing as t
from dataclasses import dataclass

from libtmux import exc
from libtmux._internal.connection import (
    ServerConnection,
    merge_connection_constraints,
)
from libtmux._internal.daemon_guard import (
    DaemonGuard,
    is_daemon_guard_refusal,
    wrap_daemon_guard,
)
from libtmux._internal.invocation import flatten_commands
from libtmux._internal.protocols import HasConnection, SupportsConnection
from libtmux.engine import AsyncTmuxEngine, TmuxRequest, TmuxResult
from libtmux.neo import get_output_format, parse_output

if t.TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = (
    "AsyncCommandResult",
    "AsyncServer",
    "AsyncSubprocessEngine",
    "adispatch",
    "adispatch_batch",
)

logger = logging.getLogger(__name__)


def _build_env(request: TmuxRequest) -> dict[str, str] | None:
    if not request.inherit_env:
        return dict(request.env) if request.env is not None else {}
    if request.env is not None:
        return {**os.environ, **request.env}
    return None


@dataclass(frozen=True, slots=True)
class AsyncCommandResult:
    r"""Decoded line and raw-byte result returned by :mod:`libtmux.aio` calls.

    Attributes
    ----------
    cmd : list[str]
        Full command vector dispatched by the engine.
    stdout : list[str]
        UTF-8 decoded standard-output lines, trailing empty lines removed.
    stderr : list[str]
        UTF-8 decoded standard-error lines, empty lines removed.
    raw_stdout : bytes
        Unmodified standard-output bytes.
    raw_stderr : bytes
        Unmodified standard-error bytes.
    returncode : int
        Exit status reported by tmux.

    Examples
    --------
    >>> from libtmux.aio import AsyncCommandResult
    >>> res = AsyncCommandResult.from_raw(
    ...     TmuxResult(argv=("tmux", "display-message", "-p", "hi"), stdout=b"hi\n"),
    ...     subcommand="display-message",
    ... )
    >>> res.stdout, res.ok
    (['hi'], True)
    """

    cmd: list[str]
    stdout: list[str]
    stderr: list[str]
    raw_stdout: bytes
    raw_stderr: bytes
    returncode: int

    @property
    def ok(self) -> bool:
        """Return ``True`` when ``returncode == 0``."""
        return self.returncode == 0

    @classmethod
    def from_raw(
        cls,
        result: TmuxResult,
        *,
        subcommand: str = "",
    ) -> AsyncCommandResult:
        """Adapt a raw :class:`~libtmux.engine.TmuxResult` with ``tmux_cmd`` parity."""
        stdout_lines = result.stdout.decode("utf-8", errors="backslashreplace").split(
            "\n"
        )
        while stdout_lines and stdout_lines[-1] == "":
            stdout_lines.pop()
        stderr_lines = [
            line
            for line in result.stderr.decode("utf-8", errors="backslashreplace").split(
                "\n"
            )
            if line
        ]
        if subcommand == "has-session" and stderr_lines and not stdout_lines:
            stdout_lines = [stderr_lines[0]]
        return cls(
            cmd=list(result.argv),
            stdout=stdout_lines,
            stderr=stderr_lines,
            raw_stdout=result.stdout,
            raw_stderr=result.stderr,
            returncode=result.returncode,
        )


class AsyncSubprocessEngine:
    r"""Asynchronous engine awaiting a ``tmux`` CLI process per request.

    Terminates and reaps child processes on cancellation and deadline expiry so
    aborted coroutines never leak orphan ``tmux`` clients.

    Parameters
    ----------
    connection : ServerConnection, optional
        Binary and server flags to dispatch through.

    Examples
    --------
    >>> import asyncio
    >>> from libtmux.aio import AsyncSubprocessEngine, adispatch
    >>> engine = AsyncSubprocessEngine.for_server(server)
    >>> asyncio.run(adispatch(engine, "display-message", "-p", "hi")).stdout
    ['hi']
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
        server_args: Sequence[str] = (),
    ) -> AsyncSubprocessEngine:
        """Build an async engine from an explicit binary path and server flags."""
        return cls(ServerConnection.of(tmux_bin, server_args))

    @classmethod
    def for_server(cls, server: t.Any) -> AsyncSubprocessEngine:
        """Build an async engine targeting *server*'s configured socket and flags."""
        return cls(ServerConnection.from_server(server))

    def with_connection(
        self,
        connection: ServerConnection,
    ) -> AsyncSubprocessEngine:
        """Return a new async engine dispatching over *connection*."""
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
        commands = request.commands
        if request.daemon_guard is not None:
            commands, _marker = wrap_daemon_guard(commands, request.daemon_guard)
        flat = flatten_commands(commands, check_imsg_limits=True)
        return self._conn.argv(
            *request.client_args,
            *flat,
            tmux_bin=request.tmux_bin,
        )

    async def execute(self, request: TmuxRequest) -> TmuxResult:
        """Execute *request* via :func:`asyncio.create_subprocess_exec`."""
        commands = request.commands
        guard_marker: str | None = None
        if request.daemon_guard is not None:
            commands, guard_marker = wrap_daemon_guard(commands, request.daemon_guard)
        flat = flatten_commands(commands, check_imsg_limits=True)
        argv = self._conn.argv(
            *request.client_args,
            *flat,
            tmux_bin=request.tmux_bin,
        )
        proc_env = _build_env(request)
        stdin_mode = (
            asyncio.subprocess.PIPE
            if request.stdin is not None
            else asyncio.subprocess.DEVNULL
        )

        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=stdin_mode,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=proc_env,
                cwd=request.cwd,
            )
        except FileNotFoundError:
            raise exc.TmuxCommandNotFound from None

        try:
            if request.timeout is not None:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(input=request.stdin),
                    timeout=request.timeout,
                )
            else:
                stdout_bytes, stderr_bytes = await process.communicate(
                    input=request.stdin
                )
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
            assert request.timeout is not None
            raise exc.TmuxCommandTimeout(argv, request.timeout) from None
        except asyncio.CancelledError:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            await process.wait()
            raise

        returncode = process.returncode if process.returncode is not None else -1
        if (
            guard_marker is not None
            and request.daemon_guard is not None
            and is_daemon_guard_refusal(stderr_bytes, guard_marker)
        ):
            raise exc.TmuxServerRestarted(
                request.daemon_guard.pid,
                request.daemon_guard.start_time,
            )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "async tmux subprocess completed",
                extra={
                    "tmux_cmd": shlex.join(argv),
                    "tmux_subcommand": request.subcommand,
                    "tmux_exit_code": returncode,
                },
            )
        return TmuxResult(
            argv=argv,
            stdout=stdout_bytes,
            stderr=stderr_bytes,
            returncode=returncode,
        )

    async def execute_batch(
        self,
        requests: Sequence[TmuxRequest],
    ) -> list[TmuxResult]:
        """Execute *requests* sequentially in order."""
        return [await self.execute(req) for req in requests]


async def adispatch(
    engine: AsyncTmuxEngine,
    *args: object,
    client_args: Sequence[str] = (),
    stdin: bytes | None = None,
    timeout: float | None = None,
    env: Mapping[str, str] | None = None,
    inherit_env: bool = True,
    cwd: pathlib.Path | str | None = None,
    daemon_guard: DaemonGuard | None = None,
) -> AsyncCommandResult:
    """Execute one tmux command over an :class:`~libtmux.engine.AsyncTmuxEngine`."""
    request = TmuxRequest.from_args(
        *args,
        client_args=client_args,
        stdin=stdin,
        timeout=timeout,
        env=env,
        inherit_env=inherit_env,
        cwd=cwd,
        daemon_guard=daemon_guard,
    )
    raw = await engine.execute(request)
    return AsyncCommandResult.from_raw(raw, subcommand=request.subcommand)


async def adispatch_batch(
    engine: AsyncTmuxEngine,
    commands: Sequence[Sequence[object] | TmuxRequest],
) -> list[AsyncCommandResult]:
    """Execute a batch of commands over *engine*, using ``execute_batch`` if present."""
    requests = [
        item if isinstance(item, TmuxRequest) else TmuxRequest.from_args(*item)
        for item in commands
    ]
    batch_fn = getattr(engine, "execute_batch", None)
    if callable(batch_fn):
        raw_results = t.cast("list[TmuxResult]", await batch_fn(requests))
    else:
        raw_results = [await engine.execute(req) for req in requests]
    return [
        AsyncCommandResult.from_raw(raw, subcommand=req.subcommand)
        for req, raw in zip(requests, raw_results, strict=True)
    ]


class AsyncServer:
    """Asynchronous counterpart to :class:`~libtmux.Server`.

    Parameters
    ----------
    socket_name : str, optional
        Server socket name (``-L``).
    socket_path : str or pathlib.Path, optional
        Server socket path (``-S``).
    config_file : str, optional
        Configuration file path (``-f``).
    colors : int, optional
        ``256`` or ``88`` terminal color flag.
    tmux_bin : str, optional
        Explicit ``tmux`` executable path.
    engine : AsyncTmuxEngine, optional
        Custom asynchronous transport; defaults to :class:`AsyncSubprocessEngine`.

    Examples
    --------
    >>> import asyncio
    >>> from libtmux.aio import AsyncServer
    >>> async_srv = AsyncServer(socket_name=server.socket_name)
    >>> asyncio.run(async_srv.is_alive())
    True
    """

    def __init__(
        self,
        socket_name: str | None = None,
        socket_path: str | pathlib.Path | None = None,
        config_file: str | None = None,
        colors: int | None = None,
        tmux_bin: str | None = None,
        *,
        engine: AsyncTmuxEngine | None = None,
    ) -> None:
        self.socket_name = socket_name
        self.socket_path = socket_path
        self.config_file = config_file
        self.colors = colors
        self.tmux_bin = tmux_bin
        self._engine = engine
        self._default_engine: AsyncSubprocessEngine | None = None
        if engine is not None and isinstance(engine, HasConnection):
            _ = self.engine

    @property
    def connection(self) -> ServerConnection:
        """Connection flags derived from this server's socket and binary fields."""
        return ServerConnection.from_server(self)

    @property
    def engine(self) -> AsyncTmuxEngine:
        """Resolved :class:`~libtmux.engine.AsyncTmuxEngine` for dispatch."""
        conn = self.connection
        injected = self._engine
        if injected is not None:
            if conn.is_unconfigured or not isinstance(injected, HasConnection):
                return injected
            resolution = merge_connection_constraints(injected.connection, conn)
            if resolution.conflicts:
                fields = ", ".join(resolution.conflicts)
                raise exc.EngineConfigurationMismatch(
                    injected,
                    f"explicit AsyncServer {fields} constraint conflicts with engine",
                    server_connection=conn,
                    engine_connection=injected.connection,
                )
            if not resolution.missing:
                return injected
            if not isinstance(injected, SupportsConnection):
                fields = ", ".join(resolution.missing)
                raise exc.EngineConfigurationMismatch(
                    injected,
                    f"pinned async engine cannot safely rebind to add {fields}",
                    server_connection=conn,
                    engine_connection=injected.connection,
                )
            return t.cast(
                "AsyncTmuxEngine",
                injected.with_connection(resolution.connection),
            )
        default = self._default_engine
        if default is None or default.connection != conn:
            default = AsyncSubprocessEngine(conn)
            self._default_engine = default
        return default

    async def cmd(
        self,
        cmd: str,
        *args: object,
        target: str | int | None = None,
        client_args: Sequence[str] = (),
        stdin: bytes | None = None,
        timeout: float | None = None,
        env: Mapping[str, str] | None = None,
        inherit_env: bool = True,
        cwd: pathlib.Path | str | None = None,
        daemon_guard: DaemonGuard | None = None,
    ) -> AsyncCommandResult:
        """Execute one tmux command asynchronously."""
        full_args = ("-t", str(target), *args) if target is not None else args
        return await adispatch(
            self.engine,
            cmd,
            *full_args,
            client_args=client_args,
            stdin=stdin,
            timeout=timeout,
            env=env,
            inherit_env=inherit_env,
            cwd=cwd,
            daemon_guard=daemon_guard,
        )

    async def cmd_batch(
        self,
        commands: Sequence[Sequence[object] | TmuxRequest],
    ) -> list[AsyncCommandResult]:
        """Execute a sequence of commands asynchronously in order."""
        return await adispatch_batch(self.engine, commands)

    async def is_alive(self) -> bool:
        """Return ``True`` when ``list-sessions`` exits zero."""
        try:
            res = await self.cmd("list-sessions")
        except exc.EngineConfigurationMismatch:
            raise
        except Exception:  # noqa: BLE001
            return False
        return res.ok

    async def raise_if_dead(self) -> None:
        """Raise :exc:`subprocess.CalledProcessError` when unreachable."""
        res = await self.cmd("list-sessions")
        if not res.ok:
            raise subprocess.CalledProcessError(
                res.returncode,
                res.cmd,
                output="\n".join(res.stdout),
                stderr="\n".join(res.stderr),
            )

    async def list_sessions(
        self,
        *,
        tmux_version: str = "3.2a",
    ) -> list[dict[str, t.Any]]:
        """Query session dictionaries asynchronously via :mod:`libtmux.neo` formats."""
        _fields, fmt = get_output_format("list-sessions", tmux_version)
        res = await self.cmd("list-sessions", f"-F{fmt}", client_args=("-u",))
        if res.stderr:
            return []
        return [
            parse_output(line, "list-sessions", tmux_version) for line in res.stdout
        ]

    async def kill(self) -> None:
        """Send ``kill-server`` asynchronously."""
        await self.cmd("kill-server")
