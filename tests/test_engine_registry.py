"""Tests for name-based engine resolution."""

from __future__ import annotations

import typing as t

import pytest

from libtmux import exc
from libtmux.engines import (
    CommandResult,
    SubprocessEngine,
    available_engines,
    create_engine,
    register_engine,
)

if t.TYPE_CHECKING:
    from libtmux.engines import CommandRequest


def test_builtin_engines_are_registered() -> None:
    assert "subprocess" in available_engines()
    assert isinstance(create_engine("subprocess"), SubprocessEngine)


def test_available_engines_is_sorted() -> None:
    names = available_engines()
    assert list(names) == sorted(names)


def test_unknown_engine_fails_closed_and_lists_options() -> None:
    with pytest.raises(exc.LibTmuxException) as excinfo:
        create_engine("does-not-exist")
    message = str(excinfo.value)
    assert "does-not-exist" in message
    assert "subprocess" in message  # names what you could have said


def test_factory_receives_kwargs() -> None:
    engine = create_engine("subprocess", server_args=("-Lfromregistry",))
    assert engine.server_args == ("-Lfromregistry",)  # type: ignore[attr-defined]


def test_third_party_can_register() -> None:
    class Custom:
        def run(self, request: CommandRequest) -> CommandResult:
            return CommandResult(cmd=("tmux", *request.args))

        def run_batch(
            self,
            requests: t.Sequence[CommandRequest],
        ) -> list[CommandResult]:
            return [self.run(r) for r in requests]

    register_engine("custom-for-test", Custom)
    try:
        assert "custom-for-test" in available_engines()
        assert isinstance(create_engine("custom-for-test"), Custom)
    finally:
        from libtmux.engines.registry import unregister_engine

        unregister_engine("custom-for-test")
    assert "custom-for-test" not in available_engines()
