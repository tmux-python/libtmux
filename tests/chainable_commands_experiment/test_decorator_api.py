"""Tests for a Django-style decorator command API."""

from __future__ import annotations

from typing_extensions import assert_type

from . import decorator_api as api
from .shared import CommandCall


def test_decorator_api_preserves_typed_call_signature() -> None:
    """Decorated command factories keep normal function-call ergonomics."""
    call = api.new_window(window_name="work", detach=True)

    assert_type(call, CommandCall)
    assert call.argv() == ("new-window", "-d", "-n", "work")


def test_decorator_api_exposes_command_metadata() -> None:
    """Command metadata can be recovered from decorated callables."""
    spec = api.get_command_spec(api.new_window)

    assert spec.name == "new-window"
    assert spec.scope == "session"
    assert spec.chainable is True


def test_decorator_api_builds_chain() -> None:
    """Decorator factories compose through the shared chain operators."""
    chain = api.new_window(window_name="work") >> api.split_window(
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
