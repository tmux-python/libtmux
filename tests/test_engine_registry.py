"""Tests for name-based engine resolution."""

from __future__ import annotations

import logging
import types
import typing as t

import pytest

from libtmux import exc
from libtmux.engines import (
    CommandResult,
    SubprocessEngine,
    available_engines,
    create_engine,
    register_engine,
    registry,
)

if t.TYPE_CHECKING:
    from libtmux.engines import CommandRequest


def test_builtin_engines_are_registered() -> None:
    """The built-in subprocess engine resolves by name."""
    assert "subprocess" in available_engines()
    assert isinstance(create_engine("subprocess"), SubprocessEngine)


def test_available_engines_is_sorted() -> None:
    """Names come back sorted, so a CLI can list them as given."""
    names = available_engines()
    assert list(names) == sorted(names)


def test_unknown_engine_fails_closed_and_lists_options() -> None:
    """An unknown name raises, naming both it and the registered alternatives."""
    with pytest.raises(exc.LibTmuxException) as excinfo:
        create_engine("does-not-exist")
    message = str(excinfo.value)
    assert "does-not-exist" in message
    assert "subprocess" in message  # names what you could have said


def test_factory_receives_kwargs() -> None:
    """Keyword arguments reach the factory rather than being dropped."""
    engine = create_engine("subprocess", server_args=("-Lfromregistry",))
    assert engine.server_args == ("-Lfromregistry",)  # type: ignore[attr-defined]


def test_broken_entry_point_is_skipped_and_reported(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A distribution whose engine will not import is skipped, but says so."""

    class BrokenEntryPoint:
        name = "broken-for-test"

        def load(self) -> t.NoReturn:
            msg = "this engine's import is broken"
            raise ImportError(msg)

    monkeypatch.setattr(registry, "_entry_points_loaded", False)
    monkeypatch.setattr(
        registry,
        "metadata",
        types.SimpleNamespace(entry_points=lambda group: [BrokenEntryPoint()]),
    )

    with caplog.at_level(logging.WARNING, logger="libtmux.engines.registry"):
        names = available_engines()

    assert "broken-for-test" not in names
    assert "subprocess" in names, "one bad engine must not hide the others"

    reported = [
        record
        for record in caplog.records
        if getattr(record, "tmux_engine_name", None) == "broken-for-test"
    ]
    assert len(reported) == 1
    assert reported[0].levelno == logging.WARNING
    assert reported[0].exc_info is not None, "the traceback is what makes it useful"


def test_third_party_can_register() -> None:
    """A registered engine resolves by name, and unregistering removes it."""

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
