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
import re
import sys
import typing as t

from libtmux import exc
from libtmux.experimental.engines.base import (
    CommandRequest,
    CommandResult,
    encode_direct_argv,
)
from libtmux.experimental.engines.connection import ServerConnection

if t.TYPE_CHECKING:
    import pathlib
    from collections.abc import Sequence


_TERMINATE_TIMEOUT = 1.0
_KILL_TIMEOUT = 1.0


def _version_from_result(result: CommandResult) -> str | None:
    """Normalize native async ``tmux -V`` output like the sync probe.

    Examples
    --------
    >>> _version_from_result(
    ...     CommandResult(cmd=("tmux", "-V"), stdout=("tmux 3.4a",))
    ... )
    '3.4'
    >>> _version_from_result(CommandResult(cmd=("tmux", "-V"), stderr=("bad",)))
    """
    from libtmux.common import TMUX_MAX_VERSION

    if result.stderr:
        if (
            sys.platform.startswith("openbsd")
            and result.stderr[0] == "tmux: unknown option -- V"
        ):
            return f"{TMUX_MAX_VERSION}-openbsd"
        return None
    if not result.stdout:
        return None
    _prefix, separator, version = result.stdout[0].partition("tmux ")
    if not separator or not version:
        return None
    if version == "master":
        return f"{TMUX_MAX_VERSION}-master"
    return re.sub(r"[a-z-]", "", version) or None


class _AsyncProcessOwner:
    """Own one subprocess and every task required to communicate or reap it."""

    __slots__ = ("_argv",)

    def __init__(self, argv: Sequence[str]) -> None:
        self._argv = tuple(argv)

    async def communicate(self) -> tuple[bytes, bytes, int]:
        """Spawn, communicate, and own exceptional cleanup for one process.

        Examples
        --------
        >>> asyncio.run(_AsyncProcessOwner(("tmux", "-V")).communicate())[2]
        0
        """
        process = await asyncio.create_subprocess_exec(
            *self._argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        communication = asyncio.create_task(
            process.communicate(),
            name="libtmux-async-subprocess-communicate",
        )
        try:
            stdout, stderr = await asyncio.shield(communication)
        except BaseException:

            async def finish_communication(timeout: float) -> bool:
                """Await pipe draining without cancelling it on timeout."""
                if communication.done():
                    await asyncio.gather(communication, return_exceptions=True)
                    return True
                done, _pending = await asyncio.wait(
                    (communication,),
                    timeout=timeout,
                )
                if not done:
                    return False
                await asyncio.gather(communication, return_exceptions=True)
                return True

            async def cleanup_process() -> None:
                """Drain pipes while performing bounded TERM-to-KILL cleanup."""
                if process.returncode is None:
                    with contextlib.suppress(Exception):
                        process.terminate()
                drained = await finish_communication(_TERMINATE_TIMEOUT)
                if drained and process.returncode is not None:
                    return
                if process.returncode is None:
                    with contextlib.suppress(Exception):
                        process.kill()
                drained = await finish_communication(_KILL_TIMEOUT)
                if drained:
                    return
                # A killed direct child closes both pipes. This fallback bounds
                # pathological inherited-pipe cases where a descendant keeps an
                # fd open after the child has exited.
                communication.cancel()
                await asyncio.gather(communication, return_exceptions=True)

            cleanup_task = asyncio.create_task(
                cleanup_process(),
                name="libtmux-async-subprocess-cleanup",
            )
            while not cleanup_task.done():
                try:
                    await asyncio.shield(cleanup_task)
                except asyncio.CancelledError:  # noqa: PERF203
                    continue
            with contextlib.suppress(asyncio.CancelledError, Exception):
                cleanup_task.result()
            raise
        return (
            stdout,
            stderr,
            process.returncode if process.returncode is not None else -1,
        )


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
        self._async_version: str | None = None
        self._async_version_probed = False
        self._async_version_lock = asyncio.Lock()

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

    async def atmux_version(self) -> str | None:
        """Probe ``tmux -V`` natively asynchronously and memoize the result.

        A cancelled probe remains retryable.

        Examples
        --------
        >>> asyncio.run(AsyncSubprocessEngine().atmux_version()) is not None
        True
        """
        if self._async_version_probed:
            return self._async_version
        async with self._async_version_lock:
            if not self._async_version_probed:
                try:
                    result = await self.run(CommandRequest.from_args("-V"))
                except exc.LibTmuxException:
                    version = None
                else:
                    version = _version_from_result(result)
                self._async_version = version
                self._async_version_probed = True
        return self._async_version

    async def run(self, request: CommandRequest) -> CommandResult:
        """Execute one tmux command asynchronously and return its result."""
        argv = encode_direct_argv(request.args)
        cmd = self._conn.argv(*argv, tmux_bin=request.tmux_bin)

        try:
            stdout_bytes, stderr_bytes, returncode = await _AsyncProcessOwner(
                cmd,
            ).communicate()
        except FileNotFoundError:
            raise exc.TmuxCommandNotFound from None

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
            returncode=returncode,
        )

    async def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Execute requests sequentially (preserving tmux command ordering)."""
        return [await self.run(req) for req in requests]

    def with_connection(self, connection: ServerConnection) -> AsyncSubprocessEngine:
        """Return an equivalent stateless async engine bound to *connection*.

        Parameters
        ----------
        connection : ServerConnection
            The connection the returned engine dispatches over.

        Returns
        -------
        AsyncSubprocessEngine
            A new engine; this engine is unchanged.

        Examples
        --------
        >>> from libtmux.experimental.engines import ServerConnection
        >>> engine = AsyncSubprocessEngine()
        >>> rebound = engine.with_connection(
        ...     ServerConnection.of(args=("-Lwork",))
        ... )
        >>> rebound.server_args, engine.server_args
        (('-Lwork',), ())
        """
        return type(self)(
            tmux_bin=connection.tmux_bin,
            server_args=connection.args,
        )

    @classmethod
    def for_server(cls, server: t.Any) -> AsyncSubprocessEngine:
        """Build an async engine bound to a live :class:`libtmux.Server`'s socket."""
        conn = ServerConnection.from_server(server)
        return cls(tmux_bin=conn.tmux_bin, server_args=conn.args)
