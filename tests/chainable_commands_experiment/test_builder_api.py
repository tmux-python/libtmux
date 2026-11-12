"""Tests for an explicit typed command builder API."""

from __future__ import annotations

from typing_extensions import assert_type

from . import builder_api as api
from .shared import CommandCall, CommandSequence


def test_builder_api_exposes_completion_friendly_methods() -> None:
    """The builder uses plain methods with explicit signatures."""
    call = api.commands.new_window(window_name="work")

    assert_type(call, CommandCall)
    assert call.argv() == ("new-window", "-d", "-n", "work")


def test_builder_api_supports_q_like_sequence_expression() -> None:
    """A Q-like immutable expression can represent ordered command sequences."""
    expr = api.sequence(
        api.commands.new_window(window_name="work"),
    ) >> api.commands.split_window(horizontal=True, percentage=50)

    assert_type(expr, CommandSequence)
    assert expr.argv() == (
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
