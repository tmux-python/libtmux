"""An asyncio engine: one subprocess per command, awaited.

The async sibling of :class:`~libtmux.engines.subprocess.SubprocessEngine`,
using :func:`asyncio.create_subprocess_exec` so a command yields to the event
loop instead of blocking it. Output handling matches the synchronous engine
exactly, so the two produce identical results for the same command.

:class:`~libtmux.Server` is synchronous and will not accept one of these; drive
it through :func:`~libtmux.common.adispatch`.
"""

from __future__ import annotations

import asyncio
import logging
import typing as t

from libtmux import exc
from libtmux.engines.base import CommandResult, encode_direct_argv
from libtmux.engines.connection import ServerConnection

if t.TYPE_CHECKING:
    import pathlib
    from collections.abc import Sequence

    from libtmux.engines.base import CommandRequest

logger = logging.getLogger(__name__)


class AsyncSubprocessEngine:
    """Execute tmux commands by awaiting the tmux CLI binary.

    Parameters
    ----------
    connection : ServerConnection, optional
        The tmux binary and connection flags to dispatch through. Defaults to
        the ambient tmux server on ``$PATH``.

    Examples
    --------
    >>> import asyncio
    >>> from libtmux.common import adispatch
    >>> from libtmux.engines import AsyncSubprocessEngine
    >>> engine = AsyncSubprocessEngine.for_server(server)
    >>> async def main():
    ...     return await adispatch(engine, "display-message", "-p", "hi")
    >>> asyncio.run(main()).stdout
    ['hi']
    """

    def __init__(self, connection: ServerConnection | None = None) -> None:
        self._conn = connection if connection is not None else ServerConnection()

    @classmethod
    def of(
        cls,
        tmux_bin: str | pathlib.Path | None = None,
        server_args: Sequence[str] = (),
    ) -> AsyncSubprocessEngine:
        """Build an engine from a binary path and raw connection flags.

        Parameters
        ----------
        tmux_bin : str or pathlib.Path, optional
            Explicit tmux binary; resolved from ``$PATH`` when ``None``.
        server_args : Sequence[str]
            Connection flags, e.g. ``("-Lwork",)``.

        Returns
        -------
        AsyncSubprocessEngine
            The engine.

        Examples
        --------
        >>> AsyncSubprocessEngine.of(server_args=["-Lwork"]).server_args
        ('-Lwork',)
        """
        return cls(ServerConnection.of(tmux_bin, server_args))

    @classmethod
    def for_server(cls, server: t.Any) -> AsyncSubprocessEngine:
        """Build an engine bound to a live :class:`libtmux.Server`'s socket.

        Parameters
        ----------
        server : typing.Any
            Any object shaped like a :class:`libtmux.Server`.

        Returns
        -------
        AsyncSubprocessEngine
            An engine reaching the same tmux server as the object API.

        Examples
        --------
        >>> AsyncSubprocessEngine.for_server(server).server_args[0].startswith("-L")
        True
        """
        return cls(ServerConnection.from_server(server))

    def with_connection(
        self,
        connection: ServerConnection,
    ) -> AsyncSubprocessEngine:
        """Return an equivalent engine dispatching over *connection*.

        Parameters
        ----------
        connection : ServerConnection
            The connection the returned engine dispatches over.

        Returns
        -------
        AsyncSubprocessEngine
            A new engine; this one is left untouched.

        Examples
        --------
        >>> from libtmux.engines import ServerConnection
        >>> engine = AsyncSubprocessEngine()
        >>> engine.with_connection(
        ...     ServerConnection.of(args=("-Lwork",))
        ... ).server_args
        ('-Lwork',)
        """
        return type(self)(connection)

    @property
    def connection(self) -> ServerConnection:
        """The tmux binary + connection flags this engine dispatches through.

        Returns
        -------
        ServerConnection
            The connection.

        Examples
        --------
        >>> AsyncSubprocessEngine.of("tmux").connection.tmux_bin
        'tmux'
        """
        return self._conn

    @property
    def server_args(self) -> tuple[str, ...]:
        """Connection flags placed before every tmux subcommand.

        Returns
        -------
        tuple[str, ...]
            The flags.

        Examples
        --------
        >>> AsyncSubprocessEngine.of(server_args=("-Ltest",)).server_args
        ('-Ltest',)
        """
        return self._conn.args

    def tmux_version(self) -> str | None:
        """Report this engine's tmux version (``tmux -V``), memoized.

        Returns
        -------
        str or None
            ``None`` when the binary is missing or unparseable.

        Examples
        --------
        >>> AsyncSubprocessEngine.for_server(server).tmux_version() is not None
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
        >>> AsyncSubprocessEngine.of("tmux", ("-Lwork",)).command_line(
        ...     CommandRequest.from_args("send-keys", "echo hi;")
        ... )
        ('tmux', '-Lwork', 'send-keys', 'echo hi\\;')
        """
        return self._conn.argv(
            *encode_direct_argv(request.args),
            tmux_bin=request.tmux_bin,
        )

    async def run(self, request: CommandRequest) -> CommandResult:
        """Await one tmux command and return its result.

        Parameters
        ----------
        request : CommandRequest
            The command.

        Returns
        -------
        CommandResult
            Structured output. ``process`` is ``None``: an
            :class:`asyncio.subprocess.Process` is not a
            :class:`subprocess.Popen`.

        Raises
        ------
        :exc:`~libtmux.exc.TmuxCommandNotFound`
            The tmux binary is missing or not executable.

        Examples
        --------
        >>> import asyncio
        >>> from libtmux.engines import AsyncSubprocessEngine, CommandRequest
        >>> engine = AsyncSubprocessEngine.for_server(server)
        >>> async def main():
        ...     return await engine.run(CommandRequest.from_args("list-sessions"))
        >>> asyncio.run(main()).ok
        True
        """
        cmd = self.command_line(request)
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            raw_stdout, raw_stderr = await process.communicate()
        except FileNotFoundError:
            raise exc.TmuxCommandNotFound from None

        stdout_lines = raw_stdout.decode("utf-8", "backslashreplace").split("\n")
        while stdout_lines and stdout_lines[-1] == "":
            stdout_lines.pop()
        stderr_lines = [
            line
            for line in raw_stderr.decode("utf-8", "backslashreplace").split("\n")
            if line
        ]

        return CommandResult(
            cmd=cmd,
            stdout=tuple(stdout_lines),
            stderr=tuple(stderr_lines),
            returncode=process.returncode if process.returncode is not None else -1,
        )

    async def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Await each request in order.

        Parameters
        ----------
        requests : Sequence[CommandRequest]
            Requests to run.

        Returns
        -------
        list[CommandResult]
            One result per request.
        """
        return [await self.run(request) for request in requests]
