"""Internal optional engine capability protocols and process handles."""

from __future__ import annotations

import contextlib
import inspect
import subprocess
import typing as t

from libtmux import exc

if t.TYPE_CHECKING:
    from libtmux._internal.connection import ServerConnection
    from libtmux.engine import TmuxEngine, TmuxRequest, TmuxResult


class ClientProcess:
    """Managed handle to a spawned, potentially blocking tmux client process.

    Parameters
    ----------
    argv : tuple[str, ...]
        Full command vector passed to :class:`subprocess.Popen`.
    process : subprocess.Popen[bytes]
        Underlying child process opened in binary mode.
    """

    __slots__ = ("_closed", "_process", "argv")

    def __init__(
        self,
        argv: tuple[str, ...],
        process: subprocess.Popen[bytes],
    ) -> None:
        self.argv = argv
        self._process = process
        self._closed = False

    @property
    def pid(self) -> int:
        """Child process identifier."""
        return self._process.pid

    @property
    def stdin(self) -> t.IO[bytes] | None:
        """Writable standard-input pipe when opened, else ``None``."""
        return self._process.stdin

    def poll(self) -> int | None:
        """Return exit status if finished, else ``None``."""
        return self._process.poll()

    def wait(self, timeout: float | None = None) -> TmuxResult:
        """Wait for completion and return the :class:`~libtmux.engine.TmuxResult`."""
        from libtmux.engine import TmuxResult

        try:
            stdout, stderr = self._process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.kill()
            assert timeout is not None
            raise exc.TmuxCommandTimeout(self.argv, timeout) from None
        self._closed = True
        return TmuxResult(
            argv=self.argv,
            stdout=stdout or b"",
            stderr=stderr or b"",
            returncode=self._process.returncode,
            _process=self._process,
        )

    def terminate(self) -> None:
        """Send ``SIGTERM`` and reap the child process."""
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
        self._close_pipes()

    def kill(self) -> None:
        """Send ``SIGKILL`` and reap the child process."""
        if self._process.poll() is None:
            self._process.kill()
            self._process.wait()
        self._close_pipes()

    def _close_pipes(self) -> None:
        if self._closed:
            return
        for stream in (self._process.stdin, self._process.stdout, self._process.stderr):
            if stream is not None:
                with contextlib.suppress(OSError):
                    stream.close()
        self._closed = True

    def __enter__(self) -> t.Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.terminate()


@t.runtime_checkable
class HasConnection(t.Protocol):
    """Engine exposing its :class:`~libtmux._internal.connection.ServerConnection`."""

    @property
    def connection(self) -> ServerConnection:
        """Connection used by this engine."""
        ...


@t.runtime_checkable
class SupportsConnection(HasConnection, t.Protocol):
    """Engine that exposes its connection and can return a rebound copy."""

    def with_connection(self, connection: ServerConnection) -> TmuxEngine:
        """Return an equivalent engine bound to *connection*."""
        ...


@t.runtime_checkable
class SupportsCommandLine(t.Protocol):
    """Engine capable of rendering the argv a request would dispatch."""

    def command_line(self, request: TmuxRequest) -> tuple[str, ...]:
        """Return the full argv for *request* without executing it."""
        ...


@t.runtime_checkable
class SupportsTmuxVersion(t.Protocol):
    """Engine capable of reporting the tmux version it targets."""

    def tmux_version(self) -> str | None:
        """Return the raw tmux version string, or ``None`` if unknown."""
        ...


@t.runtime_checkable
class SupportsBatchExecution(t.Protocol):
    """Engine implementing native multi-request batch execution."""

    def execute_batch(self, requests: t.Sequence[TmuxRequest]) -> list[TmuxResult]:
        """Execute *requests* in order and return one result per request."""
        ...


@t.runtime_checkable
class SupportsSpawnClient(t.Protocol):
    """Engine capable of spawning a non-blocking tmux client process."""

    def spawn_client(self, request: TmuxRequest) -> ClientProcess:
        """Spawn *request* without waiting for process exit."""
        ...


def guard_sync_call(
    engine: object,
    member: t.Callable[[TmuxRequest], t.Any],
    method: str,
    request: TmuxRequest,
) -> t.Any:
    """Invoke a synchronous engine method and reject awaitables cleanly.

    Closes unstarted coroutines before raising
    :exc:`~libtmux.exc.AsyncEngineMismatch` so ``RuntimeWarning`` never escapes.
    """
    if inspect.iscoroutinefunction(member):
        raise exc.AsyncEngineMismatch(engine, method)

    result = member(request)
    if inspect.isawaitable(result):
        if inspect.iscoroutine(result):
            with contextlib.suppress(BaseException):
                result.close()
        raise exc.AsyncEngineMismatch(engine, method)
    return result


def dispatch_execute(engine: TmuxEngine, request: TmuxRequest) -> TmuxResult:
    """Execute *request* on *engine*, rejecting async engines synchronously."""
    return t.cast(
        "TmuxResult",
        guard_sync_call(engine, engine.execute, "execute", request),
    )


def dispatch_command_line(
    engine: SupportsCommandLine,
    request: TmuxRequest,
) -> tuple[str, ...]:
    """Render *request* argv on *engine*, rejecting async methods synchronously."""
    return t.cast(
        "tuple[str, ...]",
        guard_sync_call(engine, engine.command_line, "command_line", request),
    )
