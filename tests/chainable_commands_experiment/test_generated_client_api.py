"""Tests for a Prisma-style generated command client API."""

from __future__ import annotations

from typing_extensions import assert_type

from . import generated_client_api as api
from .shared import CommandCall, CommandSequence


def test_generated_client_api_exposes_nested_typed_namespaces() -> None:
    """Generated namespaces provide explicit completion surfaces."""
    commands = api.GeneratedCommands()

    call = commands.window.rename(target="@1", name="editor")

    assert_type(call, CommandCall)
    assert call.argv() == ("rename-window", "-t", "@1", "editor")


def test_generated_client_api_composes_generated_calls() -> None:
    """Generated command calls still use the shared sequence IR."""
    commands = api.GeneratedCommands()
    sequence = commands.session.new_window(name="editor").then(
        commands.window.rename(target="@1", name="editor"),
    )

    assert_type(sequence, CommandSequence)
    assert sequence.argv() == (
        "new-window",
        "-d",
        "-n",
        "editor",
        ";",
        "rename-window",
        "-t",
        "@1",
        "editor",
    )
