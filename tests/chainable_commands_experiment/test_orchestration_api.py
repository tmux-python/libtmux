"""Tests for a Prefect-style command orchestration API."""

from __future__ import annotations

from typing_extensions import assert_type

from . import orchestration_api as api
from .shared import CommandCall, CommandSequence


def test_orchestration_api_submits_typed_command_tasks() -> None:
    """Submitting a task defers creation of a concrete command call."""
    task = api.CommandTask(api.rename_window)
    submitted = task.submit("@1", "editor")

    assert_type(submitted, api.SubmittedCommand)
    assert submitted.call.argv() == ("rename-window", "-t", "@1", "editor")


def test_orchestration_api_maps_submitted_commands_to_sequence() -> None:
    """Mapped submissions can still collapse to a native tmux sequence."""
    task = api.CommandTask(api.rename_window)
    submitted = task.map((("@1", "editor"), ("@2", "logs")))

    sequence = api.submitted_sequence(submitted)

    assert_type(sequence, CommandSequence)
    assert [item.call for item in submitted] == [
        CommandCall("rename-window", ("editor",), target="@1"),
        CommandCall("rename-window", ("logs",), target="@2"),
    ]
    assert sequence.argv() == (
        "rename-window",
        "-t",
        "@1",
        "editor",
        ";",
        "rename-window",
        "-t",
        "@2",
        "logs",
    )
