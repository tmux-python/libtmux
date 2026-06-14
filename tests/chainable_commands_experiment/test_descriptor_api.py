"""Tests for typed command descriptor objects."""

from __future__ import annotations

from typing_extensions import assert_type

from . import descriptor_api as api
from .shared import CommandCall


def test_descriptor_api_binds_typed_command_object() -> None:
    """Descriptors expose a concrete command object for completion."""
    commands = api.Commands()

    assert_type(commands.new_window, api.NewWindowCommand)
    assert_type(commands.split_window, api.SplitWindowCommand)


def test_descriptor_api_builds_invocation_with_metadata() -> None:
    """Bound descriptor calls produce command invocations."""
    commands = api.Commands()
    call = commands.new_window(window_name="work", detach=True)

    assert_type(call, CommandCall)
    assert commands.new_window.spec.name == "new-window"
    assert call.argv() == ("new-window", "-d", "-n", "work")


def test_descriptor_api_builds_chain() -> None:
    """Descriptor command objects compose through the shared chain type."""
    commands = api.Commands()
    chain = commands.new_window(window_name="work") >> commands.split_window(
        horizontal=True,
        percentage=50,
    )

    assert chain.argv() == (
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
