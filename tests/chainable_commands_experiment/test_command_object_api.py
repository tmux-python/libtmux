"""Tests for explicit command-object API ergonomics."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field

import pytest
from typing_extensions import assert_type

from libtmux import Session

from . import command_object_api as api
from .shared import Arg, CommandCall


class CommandObjectArgvCase(t.NamedTuple):
    """Test fixture for command object argv rendering."""

    test_id: str
    command: api.CommandValue
    expected_argv: tuple[str, ...]


COMMAND_OBJECT_ARGV_CASES: list[CommandObjectArgvCase] = [
    CommandObjectArgvCase(
        test_id="pane_split_window_target_and_percentage",
        command=api.PaneCmd.SplitWindow(
            target="%1",
            horizontal=True,
            percentage=50,
        ),
        expected_argv=("split-window", "-t", "%1", "-h", "-p", "50"),
    ),
    CommandObjectArgvCase(
        test_id="pane_capture_print_output",
        command=api.PaneCmd.CapturePane(
            target="%1",
            print_output=True,
        ),
        expected_argv=("capture-pane", "-t", "%1", "-p"),
    ),
    CommandObjectArgvCase(
        test_id="window_rename_target_keyword",
        command=api.WindowCmd.RenameWindow(
            target="@1",
            name="editor",
        ),
        expected_argv=("rename-window", "-t", "@1", "editor"),
    ),
    CommandObjectArgvCase(
        test_id="session_new_window_keyword_options",
        command=api.SessionCmd.NewWindow(
            target="$1",
            window_name="work",
            detach=True,
        ),
        expected_argv=("new-window", "-t", "$1", "-d", "-n", "work"),
    ),
    CommandObjectArgvCase(
        test_id="server_show_option_keyword",
        command=api.ServerCmd.ShowOption(
            option_name="@demo",
        ),
        expected_argv=("show-option", "-gqv", "@demo"),
    ),
]


@dataclass
class _FakeResult:
    """Small command result for command-object runner tests."""

    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)
    returncode: int = 0


@dataclass
class _FakeRunner:
    """Record command-object dispatches."""

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


@pytest.mark.parametrize(
    list(CommandObjectArgvCase._fields),
    COMMAND_OBJECT_ARGV_CASES,
    ids=[case.test_id for case in COMMAND_OBJECT_ARGV_CASES],
)
def test_command_objects_are_constructed_without_running(
    test_id: str,
    command: api.CommandValue,
    expected_argv: tuple[str, ...],
) -> None:
    """Command objects expose pure argv rendering before side effects."""
    assert test_id
    assert command.argv() == expected_argv
    assert command.to_call().argv() == expected_argv


def test_command_objects_preserve_concrete_types_and_metadata() -> None:
    """Concrete command classes keep completion-friendly types and metadata."""
    command = api.PaneCmd.SplitWindow(
        target="%1",
        horizontal=True,
        percentage=50,
    )

    assert_type(command, api.PaneCmd.SplitWindow)
    assert_type(command.to_call(), CommandCall)
    assert command.spec.name == "split-window"
    assert command.spec.scope == "pane"


def test_single_command_object_runs_through_runner_boundary() -> None:
    """A single command value can run only at the explicit boundary."""
    runner = _FakeRunner()
    command = api.PaneCmd.SplitWindow(
        target="%1",
        horizontal=True,
        percentage=50,
    )

    result = command.run(runner)

    assert result.stdout == ["ok"]
    assert runner.calls == [
        (
            "split-window",
            ("-h", "-p", 50),
            "%1",
        ),
    ]


def test_command_objects_compose_to_native_sequence() -> None:
    """Command objects compose into the shared semicolon sequence IR."""
    sequence = (
        api.SessionCmd.NewWindow(window_name="work")
        .then(api.PaneCmd.SplitWindow(horizontal=True, percentage=50))
        .then(api.WindowCmd.SelectLayout(layout="even-horizontal"))
    )

    assert_type(sequence, api.CommandObjectSequence)
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
        ";",
        "select-layout",
        "even-horizontal",
    )


def test_command_object_sequence_runs_as_one_runner_call() -> None:
    """Running a sequence batches command objects into one tmux dispatch."""
    runner = _FakeRunner()
    sequence = api.CommandSequenceBuilder(
        api.SessionCmd.NewWindow(window_name="work"),
        api.PaneCmd.SplitWindow(horizontal=True, percentage=50),
        api.WindowCmd.SelectLayout(layout="even-horizontal"),
    )

    result = sequence.run(runner)

    assert result.stdout == ["ok"]
    assert runner.calls == [
        (
            "new-window",
            (
                "-d",
                "-n",
                "work",
                ";",
                "split-window",
                "-h",
                "-p",
                "50",
                ";",
                "select-layout",
                "even-horizontal",
            ),
            None,
        ),
    ]


def test_command_object_batch_keeps_keyword_arg_completion() -> None:
    """Command namespaces provide ergonomic batching without hidden effects."""
    with api.CommandBatch() as commands:
        new_window = commands.session.new_window(window_name="work")
        split_window = commands.pane.split_window(
            horizontal=True,
            percentage=50,
        )
        commands.window.select_layout(layout="even-horizontal")

    assert_type(new_window, api.SessionCmd.NewWindow)
    assert_type(split_window, api.PaneCmd.SplitWindow)
    assert commands.to_sequence().argv() == (
        "new-window",
        "-d",
        "-n",
        "work",
        ";",
        "split-window",
        "-h",
        "-p",
        "50",
        ";",
        "select-layout",
        "even-horizontal",
    )


def test_command_object_sequence_runs_against_tmux(session: Session) -> None:
    """A command-object sequence can still use live tmux integration coverage."""
    key = "@libtmux_command_object_pattern_success"
    sequence = api.ServerCmd.SetOption(
        option_name=key,
        value="before",
    ).then(
        api.ServerCmd.SetOption(
            option_name=key,
            value="after",
        ),
    )

    result = sequence.run(session.server)
    readback = api.ServerCmd.ShowOption(option_name=key).run(session.server)

    assert result.returncode == 0
    assert readback.stdout == ["after"]


def test_command_object_sequence_stops_after_tmux_error(session: Session) -> None:
    """Native tmux sequencing semantics remain testable at integration level."""
    key = "@libtmux_command_object_pattern_error"
    sequence = (
        api.ServerCmd.SetOption(
            option_name=key,
            value="before",
        )
        .then(api.ServerCmd.HasSession(session_name="definitely_missing_session"))
        .then(
            api.ServerCmd.SetOption(
                option_name=key,
                value="after",
            ),
        )
    )

    result = sequence.run(session.server)
    readback = api.ServerCmd.ShowOption(option_name=key).run(session.server)

    assert result.returncode != 0
    assert readback.stdout == ["before"]
