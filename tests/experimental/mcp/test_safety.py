"""Tests for the MCP safety-tier core (resolver + ExpectedToolError)."""

from __future__ import annotations

import logging

import pytest

pytest.importorskip("fastmcp")


def test_resolve_safety_level_default_is_mutating() -> None:
    """An unset LIBTMUX_SAFETY defaults to the mutating tier."""
    from libtmux.experimental.mcp._safety import TAG_MUTATING, resolve_safety_level

    assert resolve_safety_level(None) == TAG_MUTATING


def test_resolve_safety_level_honors_valid_values() -> None:
    """Each recognized tier resolves to itself."""
    from libtmux.experimental.mcp._safety import (
        TAG_DESTRUCTIVE,
        TAG_MUTATING,
        TAG_READONLY,
        resolve_safety_level,
    )

    for tier in (TAG_READONLY, TAG_MUTATING, TAG_DESTRUCTIVE):
        assert resolve_safety_level(tier) == tier


def test_resolve_safety_level_invalid_fails_safe_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An invalid value falls back to readonly and warns (fail-safe)."""
    from libtmux.experimental.mcp._safety import TAG_READONLY, resolve_safety_level

    with caplog.at_level(logging.WARNING, logger="libtmux.experimental.mcp._safety"):
        assert resolve_safety_level("bogus") == TAG_READONLY
    assert any(
        record.levelno == logging.WARNING and "LIBTMUX_SAFETY" in record.getMessage()
        for record in caplog.records
    )


def test_expected_tool_error_carries_suggestion() -> None:
    """ExpectedToolError defaults to WARNING and stores a suggestion."""
    from libtmux.experimental.mcp._safety import ExpectedToolError

    err = ExpectedToolError("Pane not found", suggestion="Call list_panes.")
    assert err.log_level == logging.WARNING
    assert err.suggestion == "Call list_panes."
