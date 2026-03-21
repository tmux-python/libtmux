"""Tests for libtmux MCP server configuration."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.mcp.server import _BASE_INSTRUCTIONS, _build_instructions


class BuildInstructionsFixture(t.NamedTuple):
    """Test fixture for _build_instructions."""

    test_id: str
    tmux_pane_env: str | None
    tmux_env: str | None
    expect_agent_context: bool
    expect_pane_id_in_text: str | None
    expect_socket_name: str | None


BUILD_INSTRUCTIONS_FIXTURES: list[BuildInstructionsFixture] = [
    BuildInstructionsFixture(
        test_id="inside_tmux_full_context",
        tmux_pane_env="%42",
        tmux_env="/tmp/tmux-1000/default,12345,0",
        expect_agent_context=True,
        expect_pane_id_in_text="%42",
        expect_socket_name="default",
    ),
    BuildInstructionsFixture(
        test_id="outside_tmux_no_context",
        tmux_pane_env=None,
        tmux_env=None,
        expect_agent_context=False,
        expect_pane_id_in_text=None,
        expect_socket_name=None,
    ),
    BuildInstructionsFixture(
        test_id="pane_only_no_tmux_env",
        tmux_pane_env="%99",
        tmux_env=None,
        expect_agent_context=True,
        expect_pane_id_in_text="%99",
        expect_socket_name=None,
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
    tmux_pane_env: str | None,
    tmux_env: str | None,
    expect_agent_context: bool,
    expect_pane_id_in_text: str | None,
    expect_socket_name: str | None,
) -> None:
    """_build_instructions includes agent context when inside tmux."""
    if tmux_pane_env is not None:
        monkeypatch.setenv("TMUX_PANE", tmux_pane_env)
    else:
        monkeypatch.delenv("TMUX_PANE", raising=False)

    if tmux_env is not None:
        monkeypatch.setenv("TMUX", tmux_env)
    else:
        monkeypatch.delenv("TMUX", raising=False)

    result = _build_instructions()

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


def test_base_instructions_content() -> None:
    """_BASE_INSTRUCTIONS contains key guidance for the LLM."""
    assert "tmux hierarchy" in _BASE_INSTRUCTIONS
    assert "pane_id" in _BASE_INSTRUCTIONS
    assert "search_panes" in _BASE_INSTRUCTIONS
    assert "metadata vs content" in _BASE_INSTRUCTIONS
