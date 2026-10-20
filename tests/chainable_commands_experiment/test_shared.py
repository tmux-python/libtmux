"""Tests for the shared command-chain substrate."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field

from typing_extensions import assert_type

from libtmux import Session

from .shared import CommandCall, CommandSequence

Arg: t.TypeAlias = str | int


@dataclass
class _FakeResult:
    """Small command result for fake runner tests."""

    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)
    returncode: int = 0


@dataclass
class _FakeRunner:
    """Record calls made by CommandSequence.run()."""

    calls: list[tuple[str, tuple[Arg, ...], str | int | None]] = field(
        default_factory=list,
    )

    def cmd(
        self,
        cmd: str,
        *args: Arg,
        target: str | int | None = None,
    ) -> _FakeResult:
        """Record one command dispatch."""
        self.calls.append((cmd, args, target))
        return _FakeResult(stdout=["ok"])


def test_command_sequence_renders_tmux_semicolon_sequence() -> None:
    """Render a native tmux sequence with semicolon separator tokens."""
    sequence = CommandCall("new-window", ("-d", "-n", "work")).then(
        CommandCall("split-window", ("-h", "-p", 50)),
    )

    assert_type(sequence, CommandSequence)
    assert sequence.argv() == (
        "new-window",
        "-d",
        "-n",
        "work",
        ";",
        "split-window",
        "-h",
        "-p",
        "50",
    )


def test_command_sequence_escapes_literal_semicolon_arguments() -> None:
    """Render literal trailing semicolons as arguments, not separators."""
    sequence = CommandSequence(
        (
            CommandCall("display-message", ("value;",)),
            CommandCall("display-message", (";",)),
        ),
    )

    assert sequence.argv() == (
        "display-message",
        "value\\;",
        ";",
        "display-message",
        "\\;",
    )


def test_command_sequence_runs_as_single_runner_call() -> None:
    """Execute a sequence through one runner call."""
    runner = _FakeRunner()
    result = (
        CommandCall("new-window", ("-d", "-n", "work"))
        >> CommandCall("split-window", ("-h", "-p", 50))
    ).run(runner)

    assert result.stdout == ["ok"]
    assert runner.calls == [
        (
            "new-window",
            ("-d", "-n", "work", ";", "split-window", "-h", "-p", "50"),
            None,
        ),
    ]


def test_tmux_executes_native_command_sequence(session: Session) -> None:
    """A successful native sequence updates state in order."""
    key = "@libtmux_chainable_experiment_success"
    sequence = CommandCall("set-option", ("-gq", key, "before")).then(
        CommandCall("set-option", ("-gq", key, "after")),
    )

    result = sequence.run(session.server)

    readback = CommandSequence((CommandCall("show-option", ("-gqv", key)),)).run(
        session.server,
    )
    assert result.returncode == 0
    assert readback.stdout == ["after"]


def test_tmux_stops_native_sequence_after_error(session: Session) -> None:
    """Tmux skips later commands in a sequence after an error."""
    key = "@libtmux_chainable_experiment_error"
    sequence = (
        CommandCall("set-option", ("-gq", key, "before"))
        >> CommandCall("has-session", ("-t", "definitely_missing_session"))
        >> CommandCall("set-option", ("-gq", key, "after"))
    )

    result = sequence.run(session.server)

    readback = CommandSequence((CommandCall("show-option", ("-gqv", key)),)).run(
        session.server,
    )
    assert result.returncode != 0
    assert readback.stdout == ["before"]
