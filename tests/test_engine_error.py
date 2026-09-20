"""Engines report transport failure as a libtmux exception."""

from __future__ import annotations

import typing as t

import pytest

from libtmux import exc
from libtmux.engines import CommandResult, SubprocessEngine
from libtmux.server import Server

if t.TYPE_CHECKING:
    from libtmux.engines import CommandRequest


def test_engine_error_is_a_libtmux_exception() -> None:
    """Catching LibTmuxException still catches an engine failure."""
    assert issubclass(exc.EngineError, exc.LibTmuxException)


def test_missing_binary_is_an_engine_error() -> None:
    """A missing tmux is a transport failure, so it answers to both names."""
    assert issubclass(exc.TmuxCommandNotFound, exc.EngineError)

    engine = SubprocessEngine.of("/nonexistent/tmux")
    with pytest.raises(exc.EngineError):
        Server(engine=engine).cmd("list-sessions")


def test_existing_handlers_keep_working() -> None:
    """Widening the hierarchy must not break code catching the old name."""
    engine = SubprocessEngine.of("/nonexistent/tmux")
    with pytest.raises(exc.TmuxCommandNotFound):
        Server(engine=engine).cmd("list-sessions")


def test_an_engine_may_raise_engine_error_directly() -> None:
    """A third-party engine has a name to raise when its transport dies."""

    class DeadTransport:
        def run(self, request: CommandRequest) -> CommandResult:
            msg = "connection lost"
            raise exc.EngineError(msg)

        def run_batch(
            self,
            requests: t.Sequence[CommandRequest],
        ) -> list[CommandResult]:
            return [self.run(r) for r in requests]

    with pytest.raises(exc.EngineError, match="connection lost"):
        Server(engine=DeadTransport()).cmd("list-sessions")
