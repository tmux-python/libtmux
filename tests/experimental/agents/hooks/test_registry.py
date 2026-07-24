"""Tests for the hook registry."""

from __future__ import annotations

import pytest

from libtmux.experimental.agents.hooks.registry import get, registry


def test_registry_has_claude_and_codex() -> None:
    """registry() returns at least one hook for claude and one for codex."""
    names = {hook.name for hook in registry()}
    assert {"claude", "codex"} <= names


def test_get_unknown_raises() -> None:
    """get() raises KeyError when the requested hook name is not registered."""
    with pytest.raises(KeyError):
        get("nope")
