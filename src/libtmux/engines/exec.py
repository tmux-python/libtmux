"""Run tmux somewhere else: ``docker exec``, ``kubectl exec``, ``ssh``.

:class:`ExecEngine` puts a transport command in front of the tmux argv, so the
same :class:`~libtmux.Server` API drives a tmux server inside a container, a
pod, or on another host. Nothing about libtmux has to be installed there, only
tmux.

>>> ExecEngine.docker("build-7f3a", user="ci").command_line(
...     CommandRequest.from_args("list-sessions")
... )
('docker', 'exec', '-i', '-u', 'ci', 'build-7f3a', 'tmux', '-u', 'list-sessions')
"""

from __future__ import annotations

import shlex
import typing as t

from libtmux import exc
from libtmux.engines.base import CommandRequest, CommandResult
from libtmux.engines.connection import (
    ServerConnection,
    escape_data_semicolons,
    with_utf8,
)
from libtmux.engines.subprocess import run_argv

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from typing_extensions import Self


class ExecEngine:
    """Run tmux commands through a transport command such as ``docker exec``.

    Each request becomes one local process: *prefix*, then tmux and its
    arguments. The transport carries stdin, stdout, stderr and the exit status,
    so a tmux-side failure is data on the result exactly as with the subprocess
    engine.

    Parameters
    ----------
    prefix : sequence of str
        The transport command, such as ``("docker", "exec", "-i", "box")``.
        Empty runs tmux locally.
    tmux : str
        The tmux binary as the far side knows it.
    socket_args : sequence of str
        Connection flags for the far side, such as ``("-Lwork",)``.
        :class:`~libtmux.Server` fills them in from its own socket.
    shell : bool
        Join tmux and its arguments with :func:`shlex.join` into a single
        word. Set it for transports that re-parse their command through a
        shell, such as ``ssh`` and ``su -c``: without it, a value with a space
        or a quote is split or mangled on the way. ``docker exec`` and
        ``kubectl exec`` pass argv through untouched and need no quoting.

    Notes
    -----
    The transport never gets ``-t``: a pty rewrites newlines. ``-i`` is
    required for a request's ``input``, and the named constructors add it.
    A request's ``timeout`` kills the local transport process; the remote tmux
    command may still complete.

    Examples
    --------
    >>> engine = ExecEngine.ssh("build-host", options=("-p", "2222"))
    >>> engine.command_line(CommandRequest.from_args("display-message", "-p", "a b"))
    ('ssh', '-p', '2222', 'build-host', "tmux -u display-message -p 'a b'")
    """

    def __init__(
        self,
        prefix: Sequence[str] = (),
        *,
        tmux: str = "tmux",
        socket_args: Sequence[str] = (),
        shell: bool = False,
    ) -> None:
        self._prefix = tuple(prefix)
        self._tmux = tmux
        self._socket_args = tuple(socket_args)
        self._shell = shell
        self._version: str | None = None
        self._version_probed = False

    @classmethod
    def docker(
        cls,
        container: str,
        *,
        user: str | None = None,
        **kwargs: t.Any,
    ) -> Self:
        """Build an engine that runs tmux in a container with ``docker exec -i``.

        Parameters
        ----------
        container : str
            Container name or id.
        user : str, optional
            Run as this user (``-u``).
        **kwargs : typing.Any
            Passed to the constructor: ``tmux``, ``socket_args``, ``shell``.

        Examples
        --------
        >>> ExecEngine.docker("box").command_line(
        ...     CommandRequest.from_args("list-panes")
        ... )
        ('docker', 'exec', '-i', 'box', 'tmux', '-u', 'list-panes')
        """
        prefix = ["docker", "exec", "-i"]
        if user is not None:
            prefix += ["-u", user]
        return cls([*prefix, container], **kwargs)

    @classmethod
    def kubectl(
        cls,
        pod: str,
        *,
        namespace: str | None = None,
        container: str | None = None,
        **kwargs: t.Any,
    ) -> Self:
        """Build an engine that runs tmux in a pod with ``kubectl exec -i``.

        Parameters
        ----------
        pod : str
            Pod name.
        namespace : str, optional
            ``-n``.
        container : str, optional
            ``-c``, for a pod with several containers.
        **kwargs : typing.Any
            Passed to the constructor: ``tmux``, ``socket_args``, ``shell``.

        Examples
        --------
        >>> engine = ExecEngine.kubectl("web-0", namespace="prod", container="app")
        >>> engine.command_line(CommandRequest.from_args("list-panes"))[:-3]
        ('kubectl', 'exec', '-i', '-n', 'prod', '-c', 'app', 'web-0', '--')
        """
        prefix = ["kubectl", "exec", "-i"]
        if namespace is not None:
            prefix += ["-n", namespace]
        if container is not None:
            prefix += ["-c", container]
        return cls([*prefix, pod, "--"], **kwargs)

    @classmethod
    def ssh(
        cls,
        host: str,
        *,
        options: Sequence[str] = (),
        **kwargs: t.Any,
    ) -> Self:
        """Build an engine that runs tmux on another host with ``ssh``.

        ``ssh`` joins its arguments with spaces and hands them to the remote
        shell, so this sets ``shell=True`` unless told otherwise.

        Parameters
        ----------
        host : str
            Host, or ``user@host``.
        options : sequence of str
            Options placed before the host, such as ``("-p", "2222")``.
        **kwargs : typing.Any
            Passed to the constructor: ``tmux``, ``socket_args``, ``shell``.

        Examples
        --------
        >>> ExecEngine.ssh("ci@host").command_line(
        ...     CommandRequest.from_args("list-panes")
        ... )
        ('ssh', 'ci@host', 'tmux -u list-panes')
        """
        kwargs.setdefault("shell", True)
        return cls(["ssh", *options, host], **kwargs)

    @property
    def prefix(self) -> tuple[str, ...]:
        """The transport command placed before tmux."""
        return self._prefix

    @property
    def connection(self) -> ServerConnection:
        """The far side's tmux binary and connection flags."""
        return ServerConnection.of(self._tmux, self._socket_args)

    def with_connection(self, connection: ServerConnection) -> ExecEngine:
        """Return an equivalent engine for the server *connection* names.

        :attr:`Server.engine <libtmux.Server.engine>` calls this to give an
        engine that names no server of its own the server's socket flags. An
        explicit ``tmux_bin`` on the connection replaces this engine's tmux
        path; otherwise it keeps its own.

        Examples
        --------
        >>> from libtmux.engines import ServerConnection
        >>> ExecEngine.docker("box").with_connection(
        ...     ServerConnection.of(args=("-Lci",))
        ... ).command_line(CommandRequest.from_args("list-panes"))
        ('docker', 'exec', '-i', 'box', 'tmux', '-u', '-Lci', 'list-panes')
        """
        return type(self)(
            self._prefix,
            tmux=connection.tmux_bin or self._tmux,
            socket_args=connection.args,
            shell=self._shell,
        )

    def command_line(self, request: CommandRequest) -> tuple[str, ...]:
        """Return the local argv that runs *request*, without running it."""
        tmux_argv = with_utf8(
            (
                request.tmux_bin or self._tmux,
                *self._socket_args,
                *escape_data_semicolons(request.args),
            ),
        )
        if self._shell:
            return (*self._prefix, shlex.join(tmux_argv))
        return (*self._prefix, *tmux_argv)

    def tmux_version(self) -> str | None:
        """Report the far side's tmux version, probing once.

        Examples
        --------
        >>> ExecEngine().tmux_version() is not None
        True
        """
        if not self._version_probed:
            self._version_probed = True
            # `-V` is a tmux flag, not a command, and takes no socket flags.
            probe = (self._tmux, "-V")
            cmd = (
                (*self._prefix, shlex.join(probe))
                if self._shell
                else (*self._prefix, *probe)
            )
            try:
                result = run_argv(cmd, CommandRequest(args=("-V",), timeout=30))
            except (exc.LibTmuxException, exc.TmuxTimeout, OSError):
                return None
            if result.ok and result.stdout:
                self._version = result.stdout[0].removeprefix("tmux ").strip()
        return self._version

    def run(self, request: CommandRequest) -> CommandResult:
        """Run one tmux command through the transport.

        Raises
        ------
        ~libtmux.exc.EngineError
            The transport program itself is missing.
        ~libtmux.exc.TmuxTimeout
            ``request.timeout`` elapsed; the local transport process was killed
            and reaped.
        """
        cmd = self.command_line(request)
        try:
            return run_argv(cmd, request)
        except exc.TmuxCommandNotFound:
            msg = f"cannot run {cmd[0]!r}: command not found"
            raise exc.EngineError(msg) from None

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Run each request in order, one transport process per command."""
        return [self.run(request) for request in requests]
