"""Observe sync and async experimental engine traffic with zero-overhead composition.

Examples
--------
:func:`instrument` picks the wrapper matching the engine's dispatch style:

>>> from libtmux.experimental.engines import AsyncMockEngine, MockEngine
>>> type(instrument(MockEngine(), CountingSink())).__name__
'InstrumentedEngine'
>>> type(instrument(AsyncMockEngine(), CountingSink())).__name__
'AsyncInstrumentedEngine'
"""

from __future__ import annotations

import inspect
import time
import typing as t

from libtmux.experimental.engines.base import CommandRequest, command_count

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.engine import TmuxRequest, TmuxResult
    from libtmux.experimental.engines.base import CommandResult

__all__ = [
    "AsyncInstrumentedEngine",
    "CountingSink",
    "InstrumentedEngine",
    "Sink",
    "instrument",
]


@t.runtime_checkable
class Sink(t.Protocol):
    """Observer hooks around engine command execution."""

    def before_command(self, request: t.Any) -> t.Any:
        """Observe *request* prior to dispatch and return per-call state."""
        ...

    def after_command(
        self,
        request: t.Any,
        result: t.Any,
        state: t.Any,
    ) -> None:
        """Observe a completed *request* and its *result*."""
        ...

    def handle_error(
        self,
        request: t.Any,
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
        Number of engine requests observed.
    tmux_commands : int
        Total tmux commands carried across those requests.
    elapsed_ns : int
        Total wall-clock nanoseconds spent inside the observed engine.
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

    def before_command(self, request: t.Any) -> int:
        """Record request and command counts and return start timestamp."""
        self.requests += 1
        if isinstance(request, CommandRequest):
            self.tmux_commands += command_count(request.args)
        else:
            self.tmux_commands += len(request.commands)
        return time.perf_counter_ns()

    def after_command(self, request: t.Any, result: t.Any, state: t.Any) -> None:
        """Record elapsed time for a completed request."""
        del request, result
        self.elapsed_ns += time.perf_counter_ns() - int(state)

    def handle_error(
        self,
        request: t.Any,
        error: BaseException,
        state: t.Any,
    ) -> None:
        """Record elapsed time for a failed request."""
        del request, error
        self.elapsed_ns += time.perf_counter_ns() - int(state)


class InstrumentedEngine:
    """Wrap a synchronous engine while preserving ``run_batch`` pipelining."""

    __slots__ = ("_inner", "_sinks")

    def __init__(self, inner: t.Any, *sinks: Sink) -> None:
        self._inner = inner
        self._sinks = sinks

    @property
    def inner(self) -> t.Any:
        """The engine being observed."""
        return self._inner

    def __getattr__(self, name: str) -> t.Any:
        """Forward anything the protocol does not cover to the inner engine."""
        return getattr(self._inner, name)

    def run(self, request: CommandRequest) -> CommandResult:
        """Run one request, notifying every sink around it."""
        states = [sink.before_command(request) for sink in self._sinks]
        try:
            result: CommandResult = self._inner.run(request)
        except BaseException as error:
            for sink, state in zip(self._sinks, states, strict=True):
                sink.handle_error(request, error, state)
            raise
        for sink, state in zip(self._sinks, states, strict=True):
            sink.after_command(request, result, state)
        return result

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Run a batch via ``inner.run_batch`` when present, notifying sinks."""
        if not requests:
            return []
        if not hasattr(self._inner, "run_batch"):
            return [self.run(req) for req in requests]
        per_req_states = [
            [sink.before_command(req) for sink in self._sinks] for req in requests
        ]
        try:
            results: list[CommandResult] = self._inner.run_batch(requests)
        except BaseException as error:
            for req, states in zip(requests, per_req_states, strict=True):
                for sink, state in zip(self._sinks, states, strict=True):
                    sink.handle_error(req, error, state)
            raise
        for req, res, states in zip(requests, results, per_req_states, strict=True):
            for sink, state in zip(self._sinks, states, strict=True):
                sink.after_command(req, res, state)
        return results

    def execute(self, request: TmuxRequest) -> TmuxResult:
        """Execute a Core :class:`~libtmux.engine.TmuxRequest`."""
        states = [sink.before_command(request) for sink in self._sinks]
        try:
            result: TmuxResult = self._inner.execute(request)
        except BaseException as error:
            for sink, state in zip(self._sinks, states, strict=True):
                sink.handle_error(request, error, state)
            raise
        for sink, state in zip(self._sinks, states, strict=True):
            sink.after_command(request, result, state)
        return result


class AsyncInstrumentedEngine:
    """Wrap an asynchronous engine, preserving its concurrency.

    Examples
    --------
    >>> import asyncio
    >>> from libtmux.experimental.engines import AsyncMockEngine
    >>> from libtmux.experimental.engines.base import CommandRequest
    >>> counts = CountingSink()
    >>> engine = AsyncInstrumentedEngine(AsyncMockEngine(), counts)
    >>> _ = asyncio.run(engine.run(CommandRequest.from_args("list-panes")))
    >>> counts.requests
    1
    """

    __slots__ = ("_inner", "_sinks")

    def __init__(self, inner: t.Any, *sinks: Sink) -> None:
        self._inner = inner
        self._sinks = sinks

    @property
    def inner(self) -> t.Any:
        """The engine being observed."""
        return self._inner

    def __getattr__(self, name: str) -> t.Any:
        """Forward anything the protocol does not cover to the inner engine."""
        return getattr(self._inner, name)

    async def run(self, request: CommandRequest) -> CommandResult:
        """Await one request, notifying every sink around it."""
        states = [sink.before_command(request) for sink in self._sinks]
        try:
            result: CommandResult = await self._inner.run(request)
        except BaseException as error:
            for sink, state in zip(self._sinks, states, strict=True):
                sink.handle_error(request, error, state)
            raise
        for sink, state in zip(self._sinks, states, strict=True):
            sink.after_command(request, result, state)
        return result

    async def run_batch(
        self, requests: Sequence[CommandRequest]
    ) -> list[CommandResult]:
        """Await a batch, observing each request individually."""
        return [await self.run(request) for request in requests]


def instrument(engine: t.Any, *sinks: Sink) -> t.Any:
    """Wrap *engine* with the wrapper matching its dispatch style.

    Examples
    --------
    >>> from libtmux.experimental.engines import AsyncMockEngine, MockEngine
    >>> type(instrument(MockEngine(), CountingSink())).__name__
    'InstrumentedEngine'
    >>> type(instrument(AsyncMockEngine(), CountingSink())).__name__
    'AsyncInstrumentedEngine'
    """
    if hasattr(engine, "run") and inspect.iscoroutinefunction(engine.run):
        return AsyncInstrumentedEngine(engine, *sinks)
    return InstrumentedEngine(engine, *sinks)
