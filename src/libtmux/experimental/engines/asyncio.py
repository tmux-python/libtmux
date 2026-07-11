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
import typing as t

from libtmux import exc
from libtmux.experimental.engines.base import CommandResult
from libtmux.experimental.engines.connection import ServerConnection

if t.TYPE_CHECKING:
    import pathlib
    from collections.abc import Sequence

    from libtmux.experimental.engines.base import CommandRequest


class AsyncSubprocessEngine:
    """Execute tmux commands via :func:`asyncio.create_subprocess_exec`.

    Parameters
    ----------
    tmux_bin : str or pathlib.Path or None
        The tmux binary; resolved from ``$PATH`` when ``None``.
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

    async def run(self, request: CommandRequest) -> CommandResult:
        """Execute one tmux command asynchronously and return its result."""
        cmd = self._conn.argv(*request.args, tmux_bin=request.tmux_bin)

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
        conn = ServerConnection.from_server(server)
        return cls(tmux_bin=conn.tmux_bin, server_args=conn.args)
