"""Composable zero-overhead traffic observers for :mod:`libtmux.engine`."""

from __future__ import annotations

import time
import typing as t

from libtmux._internal.protocols import SupportsBatchExecution

if t.TYPE_CHECKING:
    from libtmux.engine import TmuxEngine, TmuxRequest, TmuxResult

__all__ = (
    "CountingSink",
    "InstrumentedEngine",
    "Sink",
    "command_count",
    "instrument",
)


def command_count(request: TmuxRequest) -> int:
    """Return the number of tmux commands carried by *request*.

    Examples
    --------
    >>> from libtmux._internal.instrumentation import command_count
    >>> from libtmux.engine import TmuxRequest
    >>> command_count(TmuxRequest.from_args("list-panes", "-a"))
    1
    >>> grouped = TmuxRequest(
    ...     commands=(("set-option", "-g", "@x", "1"), ("show-options", "-g"))
    ... )
    >>> command_count(grouped)
    2
    """
    return len(request.commands)


@t.runtime_checkable
class Sink(t.Protocol):
    """Observer hooks around engine command execution."""

    def before_command(self, request: TmuxRequest) -> t.Any:
        """Observe *request* prior to dispatch and return per-call state."""
        ...

    def after_command(
        self,
        request: TmuxRequest,
        result: TmuxResult,
        state: t.Any,
    ) -> None:
        """Observe a completed *request* and its *result*."""
        ...

    def handle_error(
        self,
        request: TmuxRequest,
        error: BaseException,
        state: t.Any,
    ) -> None:
        """Observe an exception raised during *request* dispatch."""
        ...


class CountingSink:
    """Accumulate request counts, tmux command counts, and elapsed nanoseconds.

    Attributes
    ----------
    requests : int
        Number of :class:`~libtmux.engine.TmuxRequest` dispatches observed.
    tmux_commands : int
        Total tmux commands carried across those requests.
    elapsed_ns : int
        Total wall-clock nanoseconds spent inside the observed engine.

    Examples
    --------
    >>> from libtmux._internal.instrumentation import CountingSink
    >>> sink = CountingSink()
    >>> sink.requests, sink.tmux_commands, sink.inlined
    (0, 0, 0)
    """

    __slots__ = ("elapsed_ns", "requests", "tmux_commands")

    def __init__(self) -> None:
        self.requests = 0
        self.tmux_commands = 0
        self.elapsed_ns = 0

    @property
    def inlined(self) -> int:
        """Extra tmux commands folded into multi-command requests."""
        return self.tmux_commands - self.requests

    def before_command(self, request: TmuxRequest) -> int:
        """Record request and command counts and return start timestamp."""
        self.requests += 1
        self.tmux_commands += command_count(request)
        return time.perf_counter_ns()

    def after_command(
        self,
        request: TmuxRequest,
        result: TmuxResult,
        state: t.Any,
    ) -> None:
        """Record elapsed time for a completed request."""
        del request, result
        self.elapsed_ns += time.perf_counter_ns() - int(state)

    def handle_error(
        self,
        request: TmuxRequest,
        error: BaseException,
        state: t.Any,
    ) -> None:
        """Record elapsed time for a failed request."""
        del request, error
        self.elapsed_ns += time.perf_counter_ns() - int(state)


class InstrumentedEngine:
    """Wrap a synchronous :class:`~libtmux.engine.TmuxEngine` with observer sinks.

    Delegates ``execute_batch`` to ``inner.execute_batch`` when present so
    pipelining engines such as :class:`~libtmux.engine.ControlModeEngine` keep
    their batch transport speedup under instrumentation.
    """

    __slots__ = ("_inner", "_sinks")

    def __init__(self, inner: TmuxEngine, *sinks: Sink) -> None:
        self._inner = inner
        self._sinks = sinks

    @property
    def inner(self) -> TmuxEngine:
        """Wrapped engine instance."""
        return self._inner

    @property
    def endpoint(self) -> str | None:
        """Wrapped engine endpoint."""
        return self._inner.endpoint

    def __getattr__(self, name: str) -> t.Any:
        """Forward non-protocol attributes to the wrapped engine."""
        return getattr(self._inner, name)

    def with_connection(self, connection: t.Any) -> InstrumentedEngine:
        """Rebind the inner engine while preserving attached sinks."""
        rebound = self._inner.with_connection(connection)  # type: ignore[attr-defined]
        return InstrumentedEngine(rebound, *self._sinks)

    def execute(self, request: TmuxRequest) -> TmuxResult:
        """Execute one *request*, notifying every sink around it."""
        states = [sink.before_command(request) for sink in self._sinks]
        try:
            result = self._inner.execute(request)
        except BaseException as error:
            for sink, state in zip(self._sinks, states, strict=True):
                sink.handle_error(request, error, state)
            raise
        for sink, state in zip(self._sinks, states, strict=True):
            sink.after_command(request, result, state)
        return result

    def execute_batch(self, requests: t.Sequence[TmuxRequest]) -> list[TmuxResult]:
        """Execute *requests* via ``inner.execute_batch`` while notifying sinks."""
        if not requests:
            return []
        if not isinstance(self._inner, SupportsBatchExecution):
            return [self.execute(req) for req in requests]

        per_request_states = [
            [sink.before_command(req) for sink in self._sinks] for req in requests
        ]
        try:
            results = self._inner.execute_batch(requests)
        except BaseException as error:
            for req, states in zip(requests, per_request_states, strict=True):
                for sink, state in zip(self._sinks, states, strict=True):
                    sink.handle_error(req, error, state)
            raise
        for req, res, states in zip(requests, results, per_request_states, strict=True):
            for sink, state in zip(self._sinks, states, strict=True):
                sink.after_command(req, res, state)
        return results


def instrument(engine: TmuxEngine, *sinks: Sink) -> InstrumentedEngine:
    """Wrap *engine* so *sinks* observe every command and batch."""
    return InstrumentedEngine(engine, *sinks)
