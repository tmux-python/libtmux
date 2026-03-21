"""Tests for libtmux MCP server configuration."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.mcp._utils import TAG_DESTRUCTIVE, TAG_MUTATING, TAG_READONLY
from libtmux.mcp.server import _BASE_INSTRUCTIONS, _build_instructions


class BuildInstructionsFixture(t.NamedTuple):
    """Test fixture for _build_instructions."""

    test_id: str
    safety_level: str
    tmux_pane_env: str | None
    tmux_env: str | None
    expect_agent_context: bool
    expect_pane_id_in_text: str | None
    expect_socket_name: str | None
    expect_safety_in_text: str | None


BUILD_INSTRUCTIONS_FIXTURES: list[BuildInstructionsFixture] = [
    BuildInstructionsFixture(
        test_id="inside_tmux_full_context",
        safety_level=TAG_MUTATING,
        tmux_pane_env="%42",
        tmux_env="/tmp/tmux-1000/default,12345,0",
        expect_agent_context=True,
        expect_pane_id_in_text="%42",
        expect_socket_name="default",
        expect_safety_in_text="mutating",
    ),
    BuildInstructionsFixture(
        test_id="outside_tmux_no_context",
        safety_level=TAG_MUTATING,
        tmux_pane_env=None,
        tmux_env=None,
        expect_agent_context=False,
        expect_pane_id_in_text=None,
        expect_socket_name=None,
        expect_safety_in_text="mutating",
    ),
    BuildInstructionsFixture(
        test_id="pane_only_no_tmux_env",
        safety_level=TAG_MUTATING,
        tmux_pane_env="%99",
        tmux_env=None,
        expect_agent_context=True,
        expect_pane_id_in_text="%99",
        expect_socket_name=None,
        expect_safety_in_text="mutating",
    ),
    BuildInstructionsFixture(
        test_id="readonly_safety_level",
        safety_level=TAG_READONLY,
        tmux_pane_env=None,
        tmux_env=None,
        expect_agent_context=False,
        expect_pane_id_in_text=None,
        expect_socket_name=None,
        expect_safety_in_text="readonly",
    ),
    BuildInstructionsFixture(
        test_id="destructive_safety_level",
        safety_level=TAG_DESTRUCTIVE,
        tmux_pane_env=None,
        tmux_env=None,
        expect_agent_context=False,
        expect_pane_id_in_text=None,
        expect_socket_name=None,
        expect_safety_in_text="destructive",
    ),
]


@pytest.mark.parametrize(
    BuildInstructionsFixture._fields,
    BUILD_INSTRUCTIONS_FIXTURES,
    ids=[f.test_id for f in BUILD_INSTRUCTIONS_FIXTURES],
)
def test_build_instructions(
    monkeypatch: pytest.MonkeyPatch,
    test_id: str,
    safety_level: str,
    tmux_pane_env: str | None,
    tmux_env: str | None,
    expect_agent_context: bool,
    expect_pane_id_in_text: str | None,
    expect_socket_name: str | None,
    expect_safety_in_text: str | None,
) -> None:
    """_build_instructions includes agent context and safety level."""
    if tmux_pane_env is not None:
        monkeypatch.setenv("TMUX_PANE", tmux_pane_env)
    else:
        monkeypatch.delenv("TMUX_PANE", raising=False)

    if tmux_env is not None:
        monkeypatch.setenv("TMUX", tmux_env)
    else:
        monkeypatch.delenv("TMUX", raising=False)

    result = _build_instructions(safety_level=safety_level)

    # Base instructions are always present
    assert _BASE_INSTRUCTIONS in result

    if expect_agent_context:
        assert "Agent context" in result
    else:
        assert "Agent context" not in result

    if expect_pane_id_in_text is not None:
        assert expect_pane_id_in_text in result

    if expect_socket_name is not None:
        assert expect_socket_name in result

    if expect_safety_in_text is not None:
        assert f"Safety level: {expect_safety_in_text}" in result


def test_base_instructions_content() -> None:
    """_BASE_INSTRUCTIONS contains key guidance for the LLM."""
    assert "tmux hierarchy" in _BASE_INSTRUCTIONS
    assert "pane_id" in _BASE_INSTRUCTIONS
    assert "search_panes" in _BASE_INSTRUCTIONS
    assert "metadata vs content" in _BASE_INSTRUCTIONS


def test_build_instructions_always_includes_safety() -> None:
    """_build_instructions always includes the safety level."""
    result = _build_instructions(safety_level=TAG_MUTATING)
    assert "Safety level:" in result
    assert "LIBTMUX_SAFETY" in result
