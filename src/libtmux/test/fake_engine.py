"""In-memory and recording test engines for :mod:`libtmux.test`."""

from __future__ import annotations

import typing as t

from libtmux._internal.protocols import SupportsBatchExecution
from libtmux.engine import TmuxEngine, TmuxRequest, TmuxResult

__all__ = ("FakeEngine", "RecordingEngine")


class FakeEngine:
    r"""In-memory :class:`~libtmux.engine.TmuxEngine` double needing no ``tmux``.

    Responses may be queued FIFO via :meth:`enqueue`, keyed by subcommand via
    ``responses``, or computed dynamically via ``responder``.

    Parameters
    ----------
    stdout : bytes or str
        Default standard output returned when no queued or subcommand response
        matches.
    stderr : bytes or str
        Default standard error.
    returncode : int
        Default exit status.
    endpoint : str, optional
        Simulated transport endpoint (defaults to ``None``).
    tmux_version : str, optional
        Simulated tmux release reported to version-gated callers.
    responder : callable, optional
        Custom ``(TmuxRequest) -> TmuxResult`` callback.

    Examples
    --------
    >>> from libtmux.engine import TmuxEngine, TmuxRequest
    >>> from libtmux.test import FakeEngine
    >>> fake = FakeEngine(stdout=b"$1\n")
    >>> isinstance(fake, TmuxEngine)
    True
    >>> fake.execute(TmuxRequest.from_args("list-sessions")).stdout
    b'$1\n'
    >>> len(fake.requests)
    1
    """

    def __init__(
        self,
        *,
        stdout: bytes | str = b"",
        stderr: bytes | str = b"",
        returncode: int = 0,
        endpoint: str | None = None,
        tmux_version: str | None = None,
        responder: t.Callable[[TmuxRequest], TmuxResult] | None = None,
    ) -> None:
        self._default_stdout = (
            stdout.encode("utf-8") if isinstance(stdout, str) else stdout
        )
        self._default_stderr = (
            stderr.encode("utf-8") if isinstance(stderr, str) else stderr
        )
        self._default_returncode = returncode
        self._endpoint = endpoint
        self._tmux_version = tmux_version
        self._responder = responder
        self._queue: list[TmuxResult | BaseException] = []
        self.requests: list[TmuxRequest] = []
        self.batches: list[tuple[TmuxRequest, ...]] = []

    @property
    def endpoint(self) -> str | None:
        """Simulated transport endpoint."""
        return self._endpoint

    def tmux_version(self) -> str | None:
        """Return the simulated tmux version string, or ``None``."""
        return self._tmux_version

    def enqueue(
        self,
        *,
        stdout: bytes | str = b"",
        stderr: bytes | str = b"",
        returncode: int = 0,
        error: BaseException | None = None,
    ) -> None:
        """Append a canned response or exception to the FIFO queue."""
        if error is not None:
            self._queue.append(error)
            return
        out_b = stdout.encode("utf-8") if isinstance(stdout, str) else stdout
        err_b = stderr.encode("utf-8") if isinstance(stderr, str) else stderr
        self._queue.append(
            TmuxResult(
                argv=("fake-tmux",),
                stdout=out_b,
                stderr=err_b,
                returncode=returncode,
            )
        )

    def execute(self, request: TmuxRequest) -> TmuxResult:
        """Record *request* and return the next canned or default result."""
        self.requests.append(request)
        flat = tuple(tok for cmd in request.commands for tok in cmd)
        argv = ("fake-tmux", *request.client_args, *flat)
        if self._queue:
            item = self._queue.pop(0)
            if isinstance(item, BaseException):
                raise item
            return TmuxResult(
                argv=argv,
                stdout=item.stdout,
                stderr=item.stderr,
                returncode=item.returncode,
            )
        if self._responder is not None:
            return self._responder(request)
        return TmuxResult(
            argv=argv,
            stdout=self._default_stdout,
            stderr=self._default_stderr,
            returncode=self._default_returncode,
        )

    def execute_batch(self, requests: t.Sequence[TmuxRequest]) -> list[TmuxResult]:
        """Record batch grouping and execute *requests* in order."""
        self.batches.append(tuple(requests))
        return [self.execute(req) for req in requests]


class RecordingEngine:
    """Pass-through wrapper recording requests and results around a live engine.

    Preserves ``inner.execute_batch`` so pipelined batching behavior can be
    asserted without serializing requests.
    """

    def __init__(self, inner: TmuxEngine) -> None:
        self._inner = inner
        self.requests: list[TmuxRequest] = []
        self.results: list[TmuxResult] = []
        self.batches: list[tuple[TmuxRequest, ...]] = []

    @property
    def inner(self) -> TmuxEngine:
        """Wrapped engine."""
        return self._inner

    @property
    def endpoint(self) -> str | None:
        """Wrapped engine endpoint."""
        return self._inner.endpoint

    def __getattr__(self, name: str) -> t.Any:
        """Forward non-protocol attributes to the wrapped engine."""
        return getattr(self._inner, name)

    def with_connection(self, connection: t.Any) -> RecordingEngine:
        """Rebind the wrapped engine while keeping this recorder's log lists."""
        rebound = self._inner.with_connection(connection)  # type: ignore[attr-defined]
        clone = RecordingEngine(rebound)
        clone.requests = self.requests
        clone.results = self.results
        clone.batches = self.batches
        return clone

    def execute(self, request: TmuxRequest) -> TmuxResult:
        """Record *request*, forward to ``inner.execute``, and record result."""
        self.requests.append(request)
        result = self._inner.execute(request)
        self.results.append(result)
        return result

    def execute_batch(self, requests: t.Sequence[TmuxRequest]) -> list[TmuxResult]:
        """Record batch and forward to ``inner.execute_batch`` when supported."""
        batch = tuple(requests)
        self.batches.append(batch)
        if isinstance(self._inner, SupportsBatchExecution):
            self.requests.extend(batch)
            results = self._inner.execute_batch(batch)
            self.results.extend(results)
            return results
        return [self.execute(req) for req in batch]
