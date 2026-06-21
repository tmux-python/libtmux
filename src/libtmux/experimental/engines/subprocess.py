"""The classic subprocess engine.

Executes tmux via the CLI binary, one fork per command, reproducing today's
:class:`libtmux.common.tmux_cmd` behaviour byte-for-byte: ``backslashreplace``
decoding, trailing-blank stripping, and the ``has-session`` stderr-into-stdout
fold. A tmux-side failure is returned as data (nonzero ``returncode`` plus
``stderr``); only a missing binary raises. ``server_args`` carries the
connection flags (``-L``/``-S``/``-f``/``-2``) so the engine can target a
specific tmux server.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import typing as t

from libtmux import exc
from libtmux.experimental.engines.base import CommandResult

if t.TYPE_CHECKING:
    import pathlib
    from collections.abc import Sequence

    from libtmux.experimental.engines.base import CommandRequest

logger = logging.getLogger(__name__)


class SubprocessEngine:
    """Execute tmux commands by forking the tmux CLI binary.

    Parameters
    ----------
    tmux_bin : str or pathlib.Path or None
        The tmux binary; resolved via :func:`shutil.which` when ``None``.
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
        self.tmux_bin = str(tmux_bin) if tmux_bin is not None else None
        self.server_args = tuple(server_args)
        self._resolved_bin: str | None = None

    def _resolve_bin(self) -> str:
        """Return the tmux binary path, memoized for the engine instance."""
        if self.tmux_bin is not None:
            return self.tmux_bin
        if self._resolved_bin is None:
            resolved = shutil.which("tmux")
            if resolved is None:
                raise exc.TmuxCommandNotFound
            self._resolved_bin = resolved
        return self._resolved_bin

    def run(self, request: CommandRequest) -> CommandResult:
        """Execute one tmux command via subprocess and return its result."""
        tmux_bin = request.tmux_bin or self._resolve_bin()
        cmd = [tmux_bin, *self.server_args, *request.args]

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
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

        if "has-session" in cmd and stderr_lines and not stdout_lines:
            stdout_lines = [stderr_lines[0]]

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
        server_args: list[str] = []
        if getattr(server, "socket_name", None):
            server_args.append(f"-L{server.socket_name}")
        if getattr(server, "socket_path", None):
            server_args.append(f"-S{server.socket_path}")
        if getattr(server, "config_file", None):
            server_args.append(f"-f{server.config_file}")
        colors = getattr(server, "colors", None)
        if colors == 256:
            server_args.append("-2")
        elif colors == 88:
            server_args.append("-8")
        return cls(tmux_bin=getattr(server, "tmux_bin", None), server_args=server_args)
