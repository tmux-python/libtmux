"""Tests for explicit tmux end-of-options boundaries."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.ops import (
    DisplayMessage,
    LoadBuffer,
    NewPane,
    NewSession,
    NewWindow,
    PipePane,
    RenameSession,
    RenameWindow,
    ResizePane,
    ResizeWindow,
    RespawnPane,
    RespawnWindow,
    RunShell,
    SaveBuffer,
    SelectLayout,
    SendKeys,
    SetBuffer,
    SetEnvironment,
    SetHook,
    SetOption,
    SetWindowOption,
    SourceFile,
    SplitWindow,
)

if t.TYPE_CHECKING:
    from libtmux.experimental.ops.operation import Operation


class PositionalCase(t.NamedTuple):
    """An operation and its expected positional suffix."""

    test_id: str
    operation: Operation[t.Any]
    suffix: tuple[str, ...]


POSITIONAL_CASES = (
    PositionalCase("display_message", DisplayMessage(message="-I"), ("--", "-I")),
    PositionalCase("load_buffer", LoadBuffer(path="-x"), ("--", "-x")),
    PositionalCase(
        "new_pane",
        NewPane(shell_command="-x"),
        ("--", "-x"),
    ),
    PositionalCase(
        "new_session",
        NewSession(window_shell="-x"),
        ("--", "-x"),
    ),
    PositionalCase(
        "new_window",
        NewWindow(window_shell="-x"),
        ("--", "-x"),
    ),
    PositionalCase("pipe_pane", PipePane(command_line="-x"), ("--", "-x")),
    PositionalCase("rename_session", RenameSession(name="-x"), ("--", "-x")),
    PositionalCase("rename_window", RenameWindow(name="-x"), ("--", "-x")),
    PositionalCase(
        "resize_pane",
        ResizePane(direction="D", adjustment=-1, width=80),
        ("--", "-1"),
    ),
    PositionalCase(
        "resize_window",
        ResizeWindow(direction="D", adjustment=-1, width=80),
        ("--", "-1"),
    ),
    PositionalCase("respawn_pane", RespawnPane(shell="-x"), ("--", "-x")),
    PositionalCase("respawn_window", RespawnWindow(shell="-x"), ("--", "-x")),
    PositionalCase("run_shell", RunShell(command_line="-x"), ("--", "-x")),
    PositionalCase("save_buffer", SaveBuffer(path="-x"), ("--", "-x")),
    PositionalCase("select_layout", SelectLayout(layout="-x"), ("--", "-x")),
    PositionalCase(
        "send_keys",
        SendKeys(keys="-x", enter=True),
        ("--", "-x", "Enter"),
    ),
    PositionalCase("set_buffer", SetBuffer(data="-x"), ("--", "-x")),
    PositionalCase(
        "set_environment",
        SetEnvironment(name="-x", value="-y"),
        ("--", "-x", "-y"),
    ),
    PositionalCase(
        "set_hook",
        SetHook(name="-x", hook_command="-y"),
        ("--", "-x", "-y"),
    ),
    PositionalCase(
        "set_option",
        SetOption(option="-x", value="-y"),
        ("--", "-x", "-y"),
    ),
    PositionalCase(
        "set_window_option",
        SetWindowOption(option="-x", value="-y"),
        ("--", "-x", "-y"),
    ),
    PositionalCase("source_file", SourceFile(path="-x"), ("--", "-x")),
    PositionalCase("split_window", SplitWindow(shell="-x"), ("--", "-x")),
)


OPTIONAL_POSITIONAL_CASES = (
    pytest.param(NewPane(), id="new_pane"),
    pytest.param(NewSession(), id="new_session"),
    pytest.param(NewWindow(), id="new_window"),
    pytest.param(PipePane(), id="pipe_pane"),
    pytest.param(ResizePane(direction="D"), id="resize_pane"),
    pytest.param(ResizeWindow(direction="D"), id="resize_window"),
    pytest.param(RespawnPane(), id="respawn_pane"),
    pytest.param(RespawnWindow(), id="respawn_window"),
    pytest.param(RunShell(), id="run_shell"),
    pytest.param(SelectLayout(), id="select_layout"),
)


@pytest.mark.parametrize(
    list(PositionalCase._fields),
    POSITIONAL_CASES,
    ids=[case.test_id for case in POSITIONAL_CASES],
)
def test_positional_values_follow_end_of_options(
    test_id: str,
    operation: Operation[t.Any],
    suffix: tuple[str, ...],
) -> None:
    """User positionals remain data even when they resemble tmux flags."""
    argv = operation.render()

    assert argv[-len(suffix) :] == suffix
    assert argv.count("--") == 1


@pytest.mark.parametrize("operation", OPTIONAL_POSITIONAL_CASES)
def test_absent_optional_positionals_add_no_boundary(
    operation: Operation[t.Any],
) -> None:
    """Operations without positional data do not emit a redundant marker."""
    assert "--" not in operation.render()


def test_literal_end_of_options_token_remains_positional_data() -> None:
    """A literal ``--`` value follows a distinct end-of-options marker."""
    assert SetBuffer(data="--").render() == ("set-buffer", "--", "--")
