"""Observe engine traffic without paying for it when nobody is watching.

Instrumentation here is **composed, not installed**. An
:class:`InstrumentedEngine` implements the same protocol as the engine it
wraps, so an uninstrumented program never constructs one and executes exactly
the code it executed before: no guard, no branch, no context object on the hot
path.

That differs from how the SQL ecosystem solves this, and deliberately.
SQLAlchemy exposes an event registry and pays one boolean check per call;
Django folds wrappers around each execute and builds a context mapping even
when no wrapper is registered. Both are shaped by having concrete connection
classes. :class:`~libtmux.engines.base.TmuxEngine` is a protocol, so a
decorator substitutes for the real engine anywhere one is accepted, and costs
nothing where it is absent.

The observer surface intentionally mirrors the one OpenTelemetry and Sentry
already target on SQLAlchemy -- a before hook, an after hook, and an error
hook -- so an exporter written against it needs no monkeypatching.

Examples
--------
Count what a run costs, without changing how it runs:

>>> from libtmux.engines import CommandRequest, SubprocessEngine
>>> counts = CountingSink()
>>> engine = instrument(SubprocessEngine.for_server(server), counts)
>>> _ = engine.run(CommandRequest.from_args("show-options", "-g"))
>>> counts.requests, counts.tmux_commands, counts.inlined
(1, 1, 0)

One request may carry several tmux commands. The extra ones rode along inside
an argv that spawned a single process, which is what ``inlined`` reports:

>>> from libtmux.engines import CommandSeparator
>>> counts = CountingSink()
>>> engine = instrument(SubprocessEngine.for_server(server), counts)
>>> _ = engine.run(
...     CommandRequest.from_args(
...         "set-option", "-g", "@x", "1", CommandSeparator(";"), "show-options", "-g"
...     )
... )
>>> counts.requests, counts.tmux_commands, counts.inlined
(1, 2, 1)
"""

from __future__ import annotations

import time
import typing as t

from libtmux.engines.base import command_count

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.engines.base import CommandRequest, CommandResult

__all__ = [
    "CountingSink",
    "InstrumentedEngine",
    "Sink",
    "instrument",
]


@t.runtime_checkable
class Sink(t.Protocol):
    """An observer of engine traffic.

    The three methods mirror the hook names OpenTelemetry and Sentry attach to
    on SQLAlchemy, so an exporter written for one reads naturally here.

    Whatever :meth:`before_command` returns is handed back to
    :meth:`after_command` and :meth:`handle_error` as ``state``, which lets a
    sink carry a span or a start time without keeping its own map.
    """

    def before_command(self, request: CommandRequest) -> t.Any:
        """Observe a request about to run; return per-command state."""
        ...

    def after_command(
        self, request: CommandRequest, result: CommandResult, state: t.Any
    ) -> None:
        """Observe a completed request."""
        ...

    def handle_error(
        self, request: CommandRequest, error: BaseException, state: t.Any
    ) -> None:
        """Observe a request that raised. The error still propagates."""
        ...


class CountingSink:
    """Accumulate how much tmux work passed through an engine.

    Attributes
    ----------
    requests : int
        Requests dispatched to the engine.
    tmux_commands : int
        tmux commands those requests carried, counting a command group as its
        members rather than as one.
    elapsed_ns : int
        Total wall time spent inside the engine.

    Examples
    --------
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
        """Commands that rode inside another request's argv.

        Examples
        --------
        >>> sink = CountingSink()
        >>> sink.requests, sink.tmux_commands = 3, 5
        >>> sink.inlined
        2
        """
        return self.tmux_commands - self.requests

    def before_command(self, request: CommandRequest) -> int:
        """Count the request and its commands, returning a start timestamp.

        Counting happens here, on ``request.args``, because an engine's own
        encoding flattens :class:`~libtmux.engines.base.CommandSeparator` into
        a plain string. An observer reading the encoded argv would report no
        inlining.
        """
        self.requests += 1
        self.tmux_commands += command_count(tuple(request.args))
        return time.perf_counter_ns()

    def after_command(
        self, request: CommandRequest, result: CommandResult, state: t.Any
    ) -> None:
        """Add this command's duration to the total."""
        del request, result
        self.elapsed_ns += time.perf_counter_ns() - state

    def handle_error(
        self, request: CommandRequest, error: BaseException, state: t.Any
    ) -> None:
        """Charge a failed command's duration too."""
        del request, error
        self.elapsed_ns += time.perf_counter_ns() - state


class InstrumentedEngine:
    """Wrap a synchronous engine so sinks observe every command.

    Examples
    --------
    >>> from libtmux.engines import CommandRequest, SubprocessEngine
    >>> counts = CountingSink()
    >>> engine = InstrumentedEngine(SubprocessEngine.for_server(server), counts)
    >>> _ = engine.run_batch([CommandRequest.from_args("show-options", "-g")] * 3)
    >>> counts.requests
    3
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
        """Run a batch, observing each request individually.

        The inner engine still decides how the batch is dispatched; only the
        observation is per request.
        """
        return [self.run(request) for request in requests]


def instrument(engine: t.Any, *sinks: Sink) -> t.Any:
    """Wrap *engine* so *sinks* observe every command it runs.

    Parameters
    ----------
    engine : object
        Any engine satisfying :class:`~libtmux.engines.base.TmuxEngine`.
    *sinks : Sink
        Observers, notified in the order given.

    Returns
    -------
    InstrumentedEngine
        A stand-in implementing the same protocol as *engine*.

    Examples
    --------
    >>> from libtmux.engines import SubprocessEngine
    >>> type(instrument(SubprocessEngine.for_server(server), CountingSink())).__name__
    'InstrumentedEngine'

    The wrapper forwards anything the protocol does not cover, so it stands in
    wherever the engine did:

    >>> instrument(SubprocessEngine.for_server(server)).inner.__class__.__name__
    'SubprocessEngine'
    """
    # SPIKE: the async half (AsyncInstrumentedEngine, and dispatching on
    # inspect.iscoroutinefunction(engine.run)) is deliberately absent -- this
    # seam has no async engine protocol yet. When one lands, `instrument` grows
    # the branch and the async wrapper joins it.
    return InstrumentedEngine(engine, *sinks)
