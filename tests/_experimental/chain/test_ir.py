"""Tests for the chainable-commands argv intermediate representation."""

from __future__ import annotations

import logging
import typing as t
from dataclasses import dataclass, field

import pytest

from libtmux._experimental.chain.ir import (
    CommandCall,
    CommandChain,
    CommandSpec,
)

if t.TYPE_CHECKING:
    from libtmux._experimental.chain.ir import Arg
    from libtmux.session import Session


@dataclass
class _FakeResult:
    """Minimal command result for runner tests."""

    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)
    returncode: int = 0


@dataclass
class _FakeRunner:
    """Runner that records dispatches instead of touching tmux."""

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


def _read_global_option(session: Session, name: str) -> list[str]:
    """Read a global tmux option through the experimental IR.

    Dogfoods :class:`CommandChain` for the read-back so the assertion goes
    through the typed ``CommandRunner`` protocol rather than a raw
    ``server.cmd`` call.
    """
    readback = CommandChain((CommandCall("show-option", ("-gv", name)),))
    return readback.run(session.server).stdout


def test_command_call_renders_argv() -> None:
    """A call renders its name and positional arguments in order."""
    call = CommandCall("new-window", ("-d", "-n", "work"))

    assert call.argv() == ("new-window", "-d", "-n", "work")


def test_command_call_injects_target_after_name() -> None:
    """A target renders as a ``-t`` flag immediately after the command name."""
    call = CommandCall("split-window", ("-h",), target="%1")

    assert call.argv() == ("split-window", "-t", "%1", "-h")


def test_command_call_renders_integer_arguments() -> None:
    """Integer argument tokens render via :func:`str`."""
    call = CommandCall("resize-pane", ("-y", 20), target="%1")

    assert call.argv() == ("resize-pane", "-t", "%1", "-y", "20")


def test_command_call_rejects_empty_string_target() -> None:
    """An empty-string target is rejected; ``None`` and ints are allowed."""
    with pytest.raises(ValueError, match="non-empty string or None"):
        CommandCall("kill-window", target="")

    # None (no target) and integer targets remain valid.
    assert CommandCall("list-panes").argv() == ("list-panes",)
    assert CommandCall("select-window", target=0).argv() == (
        "select-window",
        "-t",
        "0",
    )


def test_command_sequence_renders_tmux_semicolon_sequence() -> None:
    """Composed calls render with standalone ``;`` separator tokens."""
    sequence = CommandCall("new-window", ("-d",)) >> CommandCall(
        "split-window",
        ("-h",),
    )

    assert sequence.argv() == (
        "new-window",
        "-d",
        ";",
        "split-window",
        "-h",
    )


def test_command_sequence_argvs_renders_each_call_independently() -> None:
    """``argvs`` keeps per-call argv tuples for easy assertions."""
    sequence = CommandCall("rename-window", ("work",)) >> CommandCall("split-window")

    assert sequence.argvs() == (
        ("rename-window", "work"),
        ("split-window",),
    )


def test_command_sequence_escapes_literal_semicolon_arguments() -> None:
    """A literal trailing ``;`` is escaped so tmux does not split on it."""
    sequence = CommandChain(
        (CommandCall("send-keys", ("echo hi;",), target="%1"),),
    )

    assert sequence.argv() == ("send-keys", "-t", "%1", "echo hi\\;")


def test_command_sequence_rejects_empty() -> None:
    """An empty sequence is a programming error."""
    with pytest.raises(ValueError, match="at least one call"):
        CommandChain(())


def test_command_sequence_runs_as_single_runner_call() -> None:
    """``run`` dispatches the whole sequence through one runner call."""
    runner = _FakeRunner()
    sequence = CommandCall("new-window", ("-d",)) >> CommandCall("split-window")

    sequence.run(runner)

    assert runner.calls == [
        ("new-window", ("-d", ";", "split-window"), None),
    ]


def test_command_sequence_run_logs_structured_dispatch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``run`` emits a debug record carrying the rendered tmux command."""
    runner = _FakeRunner()
    sequence = CommandCall("new-window", ("-d",)) >> CommandCall("split-window")

    with caplog.at_level(logging.DEBUG, logger="libtmux._experimental.chain.ir"):
        sequence.run(runner)

    dispatched = [r for r in caplog.records if hasattr(r, "tmux_cmd")]
    assert dispatched
    record = t.cast("t.Any", dispatched[0])
    assert record.tmux_cmd == "new-window -d ; split-window"
    assert record.tmux_subcommand == "new-window"

    completed = [r for r in caplog.records if hasattr(r, "tmux_exit_code")]
    assert completed
    assert t.cast("t.Any", completed[0]).tmux_exit_code == 0


def test_command_spec_defaults_to_chainable() -> None:
    """Specs are chainable unless a command must return output immediately."""
    assert CommandSpec(name="rename-window", scope="window").chainable is True
    assert (
        CommandSpec(name="show-option", scope="server", chainable=False).chainable
        is False
    )


def test_tmux_executes_native_command_sequence(session: Session) -> None:
    """A sequence dispatches as one native tmux invocation against a server."""
    sequence = CommandCall(
        "set-option",
        ("-g", "@cc_ir_a", "1"),
    ) >> CommandCall("set-option", ("-g", "@cc_ir_b", "2"))

    result = sequence.run(session.server)

    assert result.returncode == 0
    assert _read_global_option(session, "@cc_ir_b") == ["2"]


def test_tmux_stops_native_sequence_after_error(session: Session) -> None:
    """Tmux skips later commands in a sequence once one errors."""
    sequence = CommandCall(
        "set-option",
        ("-g", "@cc_ir_marker", "set"),
    ) >> CommandCall("has-session", ("-t", "cc_definitely_missing_session"))

    result = sequence.run(session.server)

    assert result.returncode != 0
    # The first command ran before the erroring one stopped the rest.
    assert _read_global_option(session, "@cc_ir_marker") == ["set"]
