"""A real asynchronous subprocess engine.

Built on :func:`asyncio.create_subprocess_exec` -- genuine async process I/O,
not a thread wrapper around the sync engine. On cancellation it terminates the
child process before propagating :class:`asyncio.CancelledError`, so a cancelled
``arun`` leaks no tmux process. It mirrors the classic engine's output handling
(``backslashreplace`` decoding, trailing-blank stripping) so it returns the
*same* typed result the classic engine does.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import typing as t

from libtmux import exc
from libtmux.experimental.engines.base import CommandResult

if t.TYPE_CHECKING:
    import pathlib
    from collections.abc import Sequence

    from libtmux.experimental.engines.base import CommandRequest


class AsyncSubprocessEngine:
    """Execute tmux commands via :func:`asyncio.create_subprocess_exec`.

    Parameters
    ----------
    tmux_bin : str or pathlib.Path or None
        The tmux binary; resolved via :func:`shutil.which` when ``None``.
    server_args : Sequence[str]
        Connection flags inserted before the command.

    Examples
    --------
    >>> import asyncio
    >>> from libtmux.experimental.ops import SendKeys, arun
    >>> from libtmux.experimental.ops._types import PaneId
    >>> engine = AsyncSubprocessEngine()
    >>> hasattr(engine, "run") and hasattr(engine, "run_batch")
    True
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

    async def run(self, request: CommandRequest) -> CommandResult:
        """Execute one tmux command asynchronously and return its result."""
        tmux_bin = request.tmux_bin or self._resolve_bin()
        cmd = [tmux_bin, *self.server_args, *request.args]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            raise exc.TmuxCommandNotFound from None

        try:
            stdout_bytes, stderr_bytes = await process.communicate()
        except asyncio.CancelledError:
            # The child may have already exited (terminate races the reap);
            # suppress so the cancellation propagates, not ProcessLookupError.
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            await process.wait()
            raise

        stdout = stdout_bytes.decode(errors="backslashreplace")
        stderr = stderr_bytes.decode(errors="backslashreplace")

        stdout_lines = stdout.split("\n")
        while stdout_lines and stdout_lines[-1] == "":
            stdout_lines.pop()
        stderr_lines = [line for line in stderr.split("\n") if line]

        return CommandResult(
            cmd=tuple(cmd),
            stdout=tuple(stdout_lines),
            stderr=tuple(stderr_lines),
            returncode=process.returncode if process.returncode is not None else -1,
        )

    async def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Execute requests sequentially (preserving tmux command ordering)."""
        return [await self.run(req) for req in requests]

    @classmethod
    def for_server(cls, server: t.Any) -> AsyncSubprocessEngine:
        """Build an async engine bound to a live :class:`libtmux.Server`'s socket."""
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
