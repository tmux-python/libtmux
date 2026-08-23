"""Observe async engine traffic, reusing the seam's synchronous wrapper.

:mod:`libtmux.engines.instrumentation` owns the observer surface and the
synchronous wrapper, because both need nothing beyond
:class:`~libtmux.engines.base.TmuxEngine`. This module adds the half that
cannot live there: an asynchronous engine protocol is experimental, so its
wrapper is too.

:class:`~libtmux.engines.instrumentation.Sink`,
:class:`~libtmux.engines.instrumentation.CountingSink`, and
:class:`~libtmux.engines.instrumentation.InstrumentedEngine` are re-exported so
a caller reaching for the experimental engines finds the whole surface in one
place.

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

import typing as t

from libtmux.engines.instrumentation import (
    CountingSink,
    InstrumentedEngine,
    Sink,
)

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.engines.base import CommandRequest, CommandResult

__all__ = [
    "AsyncInstrumentedEngine",
    "CountingSink",
    "InstrumentedEngine",
    "Sink",
    "instrument",
]


class AsyncInstrumentedEngine:
    """Wrap an asynchronous engine, preserving its concurrency.

    Sink callbacks are synchronous and must stay cheap: they run on the event
    loop between the await points, so a blocking sink would stall it.

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

    This shadows :func:`libtmux.engines.instrumentation.instrument`, which knows
    only the synchronous wrapper because the seam has no async engine protocol.

    Parameters
    ----------
    engine : object
        Any engine satisfying the sync or async engine protocol.
    *sinks : Sink
        Observers, notified in the order given.

    Returns
    -------
    InstrumentedEngine or AsyncInstrumentedEngine
        A stand-in implementing the same protocol as *engine*.

    Examples
    --------
    >>> from libtmux.experimental.engines import AsyncMockEngine, MockEngine
    >>> type(instrument(MockEngine(), CountingSink())).__name__
    'InstrumentedEngine'
    >>> type(instrument(AsyncMockEngine(), CountingSink())).__name__
    'AsyncInstrumentedEngine'
    """
    import inspect

    if inspect.iscoroutinefunction(engine.run):
        return AsyncInstrumentedEngine(engine, *sinks)
    return InstrumentedEngine(engine, *sinks)
