"""Tests for the hook registry + canonical event map."""

from __future__ import annotations

import pytest

from libtmux.experimental.agents.hooks.base import EVENT_STATE
from libtmux.experimental.agents.hooks.registry import get, registry


def test_event_state_map_is_canonical() -> None:
    """EVENT_STATE maps the four canonical lifecycle events to state strings."""
    assert EVENT_STATE["turn_start"] == "running"
    assert EVENT_STATE["needs_approval"] == "awaiting_input"
    assert EVENT_STATE["turn_end"] == "done"


def test_registry_has_claude_and_codex() -> None:
    """registry() returns at least one hook for claude and one for codex."""
    names = {hook.name for hook in registry()}
    assert {"claude", "codex"} <= names


def test_get_unknown_raises() -> None:
    """get() raises KeyError when the requested hook name is not registered."""
    with pytest.raises(KeyError):
        get("nope")
