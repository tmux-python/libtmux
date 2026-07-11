"""The classic subprocess engine.

Executes tmux via the CLI binary, one fork per command, mirroring today's
:class:`libtmux.common.tmux_cmd` output handling: ``backslashreplace`` decoding
and trailing-blank stripping. A tmux-side failure is returned as data (nonzero
``returncode`` plus ``stderr``); only a missing binary raises. The engine holds a
:class:`~.connection.ServerConnection`, which owns the tmux binary and the
connection flags (``-L``/``-S``/``-f``/``-2``) that target one tmux server.
"""

from __future__ import annotations

import subprocess
import typing as t

from libtmux import exc
from libtmux.experimental.engines.base import CommandResult
from libtmux.experimental.engines.connection import ServerConnection

if t.TYPE_CHECKING:
    import pathlib
    from collections.abc import Sequence

    from libtmux.experimental.engines.base import CommandRequest


class SubprocessEngine:
    """Execute tmux commands by forking the tmux CLI binary.

    Parameters
    ----------
    tmux_bin : str or pathlib.Path or None
        The tmux binary; resolved from ``$PATH`` when ``None``.
    server_args : Sequence[str]
        Connection flags inserted before the command (e.g.
        ``("-L", "test")`` or ``("-Lmysocket",)``).
    """

    def __init__(
        self,
        tmux_bin: str | pathlib.Path | None = None,
        *,
        server_args: Sequence[str] = (),
    ) -> None:
        self._conn = ServerConnection.of(tmux_bin, server_args)

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
        """Connection flags placed before every tmux subcommand."""
        return self._conn.args

    def tmux_version(self) -> str | None:
        """Report this engine's tmux version (``tmux -V``), memoized.

        Returns ``None`` when the binary is missing or its version cannot be
        parsed, so version resolution degrades to "assume latest".
        """
        return self._conn.tmux_version()

    def run(self, request: CommandRequest) -> CommandResult:
        """Execute one tmux command via subprocess and return its result."""
        cmd = self._conn.argv(*request.args, tmux_bin=request.tmux_bin)

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

        stdout_lines = stdout.split("\n")
        while stdout_lines and stdout_lines[-1] == "":
            stdout_lines.pop()
        stderr_lines = [line for line in stderr.split("\n") if line]

        return CommandResult(
            cmd=tuple(cmd),
            stdout=tuple(stdout_lines),
            stderr=tuple(stderr_lines),
            returncode=returncode,
        )

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Execute each request in order (subprocess forks per call)."""
        return [self.run(req) for req in requests]

    @classmethod
    def for_server(cls, server: t.Any) -> SubprocessEngine:
        """Build an engine bound to a live :class:`libtmux.Server`'s socket.

        Mirrors :meth:`libtmux.Server.cmd`'s connection-flag construction so the
        engine talks to the same tmux server as the object API.
        """
        conn = ServerConnection.from_server(server)
        return cls(tmux_bin=conn.tmux_bin, server_args=conn.args)
