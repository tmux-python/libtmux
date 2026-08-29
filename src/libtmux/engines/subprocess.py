"""The default engine: one ``fork``/``exec`` of the tmux CLI per command.

Mirrors the output handling libtmux has always had -- ``backslashreplace``
decoding, trailing-blank stripping on stdout, blank filtering on stderr. A
tmux-side failure comes back as data (nonzero ``returncode`` plus ``stderr``);
only a missing binary raises.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
import typing as t

from libtmux import exc
from libtmux.engines.base import CommandResult, encode_direct_argv
from libtmux.engines.connection import ServerConnection

if t.TYPE_CHECKING:
    import pathlib
    from collections.abc import Sequence

    from libtmux.engines.base import CommandRequest

logger = logging.getLogger(__name__)


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
    ['hi']
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
        """Report this engine's tmux version (``tmux -V``), memoized.

        Returns
        -------
        str or None
            ``None`` when the binary is missing or its version cannot be
            parsed, so version resolution degrades to "assume latest".

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
        ...     CommandRequest.from_args("send-keys", "echo hi;")
        ... )
        ('tmux', '-Lwork', 'send-keys', 'echo hi\\;')
        """
        return self._conn.argv(
            *encode_direct_argv(request.args),
            tmux_bin=request.tmux_bin,
        )

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
        cmd = self.command_line(request)

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="backslashreplace",
            )
            stdout, stderr = process.communicate()
            returncode = process.returncode
        except FileNotFoundError:
            raise exc.TmuxCommandNotFound from None
        except Exception:
            logger.error(  # noqa: TRY400
                "tmux subprocess failed",
                extra={"tmux_cmd": shlex.join(cmd)},
            )
            raise

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
