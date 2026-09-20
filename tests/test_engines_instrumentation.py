"""Tests for observing engine traffic at the command execution seam."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.engines import (
    CommandRequest,
    CommandSeparator,
    CountingSink,
    InstrumentedEngine,
    Sink,
    SubprocessEngine,
    TmuxEngine,
    command_count,
    instrument,
)
from libtmux.engines.base import CommandResult

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.server import Server


class _ExplodingEngine:
    """An engine whose every command raises, to exercise the error hook."""

    def run(self, request: CommandRequest) -> CommandResult:
        msg = f"boom: {request.args[0]}"
        raise RuntimeError(msg)

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        return [self.run(request) for request in requests]


def test_instrumented_engine_satisfies_the_engine_protocol() -> None:
    """A wrapper stands in wherever the engine it wraps was accepted.

    This is the property the whole design rests on: observation is a
    substitution, so nothing downstream needs to know it happened.
    """
    engine = InstrumentedEngine(_ExplodingEngine(), CountingSink())

    assert isinstance(engine, TmuxEngine)


def test_counting_sink_separates_requests_from_tmux_commands(server: Server) -> None:
    """A command group is one request carrying several tmux commands."""
    counts = CountingSink()
    engine = instrument(SubprocessEngine.for_server(server), counts)

    engine.run(CommandRequest.from_args("show-options", "-g"))
    engine.run(
        CommandRequest.from_args(
            "set-option",
            "-g",
            "@spike",
            "1",
            CommandSeparator(";"),
            "show-options",
            "-g",
        ),
    )

    assert counts.requests == 2
    assert counts.tmux_commands == 3
    assert counts.inlined == 1


def test_counting_happens_on_args_not_the_encoded_argv(server: Server) -> None:
    """Inlining is only visible before an engine flattens the separator.

    ``CommandSeparator`` is a ``str`` subclass, so any encoding that renders
    argv to plain strings erases the distinction. Counting on ``request.args``
    is what keeps the inlined figure meaningful.
    """
    grouped = CommandRequest.from_args(
        "set-option",
        "-g",
        "@spike",
        "1",
        CommandSeparator(";"),
        "show-options",
        "-g",
    )
    flattened = tuple(str(token) for token in grouped.args)

    assert command_count(tuple(grouped.args)) == 2
    assert command_count(flattened) == 1

    counts = CountingSink()
    instrument(SubprocessEngine.for_server(server), counts).run(grouped)
    assert counts.tmux_commands == 2


def test_a_literal_semicolon_is_data_not_a_boundary() -> None:
    """A ``";"`` a caller meant as text must not inflate the command count."""
    assert command_count(("send-keys", "-t", "%0", "echo hi ; echo bye")) == 1
    assert command_count(("send-keys", ";")) == 1
    assert command_count(("a", CommandSeparator(";"), "b")) == 2


def test_error_hook_fires_and_the_error_still_propagates() -> None:
    """A sink observes the failure; it does not swallow it."""
    seen: list[BaseException] = []

    class _Recording:
        def before_command(self, request: CommandRequest) -> None:
            del request

        def after_command(
            self, request: CommandRequest, result: CommandResult, state: t.Any
        ) -> None:  # pragma: no cover - the command raises
            del request, result, state

        def handle_error(
            self, request: CommandRequest, error: BaseException, state: t.Any
        ) -> None:
            del request, state
            seen.append(error)

    sink = _Recording()
    assert isinstance(sink, Sink)
    engine = InstrumentedEngine(_ExplodingEngine(), sink)

    with pytest.raises(RuntimeError, match="boom: kill-server"):
        engine.run(CommandRequest.from_args("kill-server"))

    assert len(seen) == 1
    assert isinstance(seen[0], RuntimeError)


def test_a_failed_command_is_still_charged_time() -> None:
    """Duration accrues whether the command succeeded or raised."""
    counts = CountingSink()
    engine = InstrumentedEngine(_ExplodingEngine(), counts)

    with pytest.raises(RuntimeError):
        engine.run(CommandRequest.from_args("kill-server"))

    assert counts.requests == 1
    assert counts.elapsed_ns > 0


def test_sinks_are_notified_in_the_order_given(server: Server) -> None:
    """Ordering is part of the contract; an exporter may depend on it."""
    order: list[str] = []

    class _Named:
        def __init__(self, name: str) -> None:
            self.name = name

        def before_command(self, request: CommandRequest) -> None:
            del request
            order.append(self.name)

        def after_command(
            self, request: CommandRequest, result: CommandResult, state: t.Any
        ) -> None:
            del request, result, state

        def handle_error(
            self, request: CommandRequest, error: BaseException, state: t.Any
        ) -> None:  # pragma: no cover - the command succeeds
            del request, error, state

    engine = instrument(
        SubprocessEngine.for_server(server), _Named("first"), _Named("second")
    )
    engine.run(CommandRequest.from_args("show-options", "-g"))

    assert order == ["first", "second"]


def test_the_wrapper_forwards_what_the_protocol_does_not_cover(
    server: Server,
) -> None:
    """An engine's own surface stays reachable through the wrapper."""
    inner = SubprocessEngine.for_server(server)
    engine = instrument(inner, CountingSink())

    assert engine.inner is inner
    assert engine.connection == inner.connection


def test_an_unwrapped_program_constructs_nothing(server: Server) -> None:
    """The zero-overhead claim, stated as a test rather than as prose.

    Nothing in the seam creates a sink or a wrapper on its own, so a caller
    that never asks for instrumentation runs the engine it built.
    """
    engine = SubprocessEngine.for_server(server)

    assert not isinstance(engine, InstrumentedEngine)
    assert type(engine).run is SubprocessEngine.run
