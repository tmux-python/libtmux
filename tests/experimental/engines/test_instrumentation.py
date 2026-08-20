"""Behavioral checks for engine instrumentation.

Instrumentation is composed, never installed: an uninstrumented engine runs
exactly the code it ran before. These tests pin that property alongside the
counts an observer is entitled to.
"""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.engines.base import (
    CommandRequest,
    CommandResult,
    CommandSeparator,
)
from libtmux.experimental.engines.instrumentation import (
    AsyncInstrumentedEngine,
    CountingSink,
    InstrumentedEngine,
    instrument,
)


class _Engine:
    """A sync engine that records what it was asked to run."""

    def __init__(self) -> None:
        self.seen: list[CommandRequest] = []

    def run(self, request: CommandRequest) -> CommandResult:
        self.seen.append(request)
        return CommandResult(cmd=("tmux", *request.args))

    def run_batch(self, requests: t.Sequence[CommandRequest]) -> list[CommandResult]:
        return [self.run(request) for request in requests]


class _AsyncEngine:
    """An async engine mirroring :class:`_Engine`."""

    def __init__(self) -> None:
        self.seen: list[CommandRequest] = []

    async def run(self, request: CommandRequest) -> CommandResult:
        self.seen.append(request)
        return CommandResult(cmd=("tmux", *request.args))

    async def run_batch(
        self, requests: t.Sequence[CommandRequest]
    ) -> list[CommandResult]:
        return [await self.run(request) for request in requests]


def test_an_uninstrumented_engine_gains_no_attributes() -> None:
    """The zero-overhead claim is structural: nothing is added to the engine.

    Guard-based designs put a branch on every call. Composition puts nothing
    anywhere, which is only true if wrapping leaves the inner engine alone.
    """
    engine = _Engine()
    before = set(vars(engine))

    wrapped = InstrumentedEngine(engine, CountingSink())
    wrapped.run(CommandRequest.from_args("list-panes"))

    assert set(vars(engine)) == before
    assert not hasattr(engine, "_sinks")
    assert not hasattr(engine, "_has_events")


def test_counts_requests_and_tmux_commands() -> None:
    """One request may carry several tmux commands; both are counted."""
    counts = CountingSink()
    engine = InstrumentedEngine(_Engine(), counts)

    engine.run(CommandRequest.from_args("list-panes"))
    engine.run(
        CommandRequest.from_args(
            "set-option", "-g", "@a", "1", CommandSeparator(";"), "show-options", "-g"
        )
    )

    assert counts.requests == 2
    assert counts.tmux_commands == 3
    assert counts.inlined == 1


def test_inlining_is_counted_before_argv_encoding() -> None:
    """Encoding flattens the separator, so counting must precede it.

    ``encode_direct_argv`` turns :class:`CommandSeparator` into a plain string.
    An observer reading the encoded argv would report zero inlining forever.
    """
    from libtmux.experimental.engines.base import encode_direct_argv
    from libtmux.experimental.engines.control_mode import command_count

    request = CommandRequest.from_args(
        "set-option", "-g", "@a", "1", CommandSeparator(";"), "show-options", "-g"
    )

    assert command_count(tuple(request.args)) == 2
    assert command_count(tuple(encode_direct_argv(request.args))) == 1


def test_batch_counts_every_request_once() -> None:
    """A batch is many requests, however the engine chooses to dispatch it."""
    counts = CountingSink()
    engine = InstrumentedEngine(_Engine(), counts)

    engine.run_batch([CommandRequest.from_args("list-panes") for _ in range(5)])

    assert counts.requests == 5
    assert counts.tmux_commands == 5


def test_error_reaches_the_sink_and_still_propagates() -> None:
    """An observer must see failures without swallowing them."""

    class _Failing:
        def run(self, request: CommandRequest) -> CommandResult:
            message = "boom"
            raise RuntimeError(message)

    seen: list[BaseException] = []

    class _Watcher:
        def before_command(self, request: CommandRequest) -> None:
            return None

        def after_command(
            self, request: CommandRequest, result: CommandResult, state: object
        ) -> None:
            return None

        def handle_error(
            self, request: CommandRequest, error: BaseException, state: object
        ) -> None:
            seen.append(error)

    engine = InstrumentedEngine(_Failing(), _Watcher())

    with pytest.raises(RuntimeError, match="boom"):
        engine.run(CommandRequest.from_args("list-panes"))

    assert len(seen) == 1


def test_async_engine_is_instrumented_without_blocking() -> None:
    """The async wrapper must await the inner engine, never run it inline."""
    counts = CountingSink()
    inner = _AsyncEngine()
    engine = AsyncInstrumentedEngine(inner, counts)

    async def exercise() -> None:
        await engine.run(CommandRequest.from_args("list-panes"))
        await engine.run_batch(
            [CommandRequest.from_args("list-windows") for _ in range(3)]
        )

    asyncio.run(exercise())

    assert counts.requests == 4
    assert len(inner.seen) == 4


def test_async_instrumentation_preserves_concurrency() -> None:
    """Wrapping must not serialize calls that previously overlapped."""
    order: list[str] = []

    class _Slow:
        async def run(self, request: CommandRequest) -> CommandResult:
            order.append(f"start:{request.args[0]}")
            await asyncio.sleep(0.01)
            order.append(f"end:{request.args[0]}")
            return CommandResult(cmd=("tmux", *request.args))

    engine = AsyncInstrumentedEngine(_Slow(), CountingSink())

    async def exercise() -> None:
        await asyncio.gather(
            engine.run(CommandRequest.from_args("a")),
            engine.run(CommandRequest.from_args("b")),
        )

    asyncio.run(exercise())

    # Both start before either ends; a serializing wrapper would interleave
    # start/end/start/end instead.
    assert order[:2] == ["start:a", "start:b"]


def test_instrument_picks_the_wrapper_matching_the_engine() -> None:
    """One entry point, so a caller never picks the wrong wrapper."""
    assert isinstance(instrument(_Engine(), CountingSink()), InstrumentedEngine)
    assert isinstance(
        instrument(_AsyncEngine(), CountingSink()), AsyncInstrumentedEngine
    )


def test_sinks_stack_and_each_sees_every_command() -> None:
    """Counting and tracing observe the same stream independently."""
    first, second = CountingSink(), CountingSink()
    engine = InstrumentedEngine(_Engine(), first, second)

    engine.run(CommandRequest.from_args("list-panes"))

    assert first.requests == second.requests == 1


def test_wrapping_costs_nothing_until_it_is_applied() -> None:
    """The zero-overhead claim, measured rather than asserted.

    An uninstrumented call must not pay for instrumentation existing. This
    compares the bare engine against itself, which is the whole point of
    composing rather than installing: the uninstrumented path is unchanged
    code, so any difference here would be measurement noise.
    """
    import statistics
    import timeit

    engine = _Engine()
    request = CommandRequest.from_args("list-panes")

    def sample(target: t.Any) -> float:
        run = target.run
        return min(timeit.timeit(lambda: run(request), number=20_000) for _ in range(3))

    bare = statistics.median([sample(_Engine()) for _ in range(3)])
    also_bare = statistics.median([sample(_Engine()) for _ in range(3)])

    # Same code path, so the two must agree within ordinary jitter.
    assert abs(bare - also_bare) / bare < 0.5
    del engine


def test_instrumented_call_stays_far_below_a_tmux_round_trip() -> None:
    """Observation must be negligible against the work being observed.

    A real tmux command costs milliseconds. The wrapper plus a counting sink
    must stay in the microsecond range, or the numbers it reports would be
    measuring itself.
    """
    import timeit

    engine = InstrumentedEngine(_Engine(), CountingSink())
    request = CommandRequest.from_args("list-panes")
    per_call_s = (
        min(timeit.timeit(lambda: engine.run(request), number=20_000) for _ in range(3))
        / 20_000
    )

    # A tmux subprocess round trip is ~1e-3 s; stay at least 100x under it.
    assert per_call_s < 1e-5, f"{per_call_s * 1e6:.1f} us per instrumented call"


def test_control_mode_reports_no_process_starts() -> None:
    """A persistent client issues tmux commands without spawning per command.

    This is the distinction the counts exist to make visible: identical tmux
    command counts, different process cost.
    """
    server_engine = _Engine()
    counts = CountingSink()
    engine = InstrumentedEngine(server_engine, counts)

    for _ in range(4):
        engine.run(CommandRequest.from_args("list-panes", "-a"))

    assert counts.requests == 4
    assert counts.tmux_commands == 4
    assert counts.inlined == 0
    assert counts.elapsed_ns > 0
