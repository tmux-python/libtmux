"""Tests for the AgentState enum and Agent record."""

from __future__ import annotations

from libtmux.experimental.agents.state import Agent, AgentState


def test_from_signal_maps_known_and_unknown() -> None:
    """Test AgentState.from_signal maps known and unknown states."""
    assert AgentState.from_signal("running") is AgentState.RUNNING
    assert AgentState.from_signal("awaiting_input") is AgentState.AWAITING_INPUT
    assert AgentState.from_signal("idle") is AgentState.IDLE
    assert AgentState.from_signal("garbage") is AgentState.UNKNOWN


def test_agent_helpers() -> None:
    """Test Agent properties is_awaiting and is_running."""
    agent = Agent(
        pane_id="%1",
        key="%1",
        name="claude",
        state=AgentState.AWAITING_INPUT,
        since=1.0,
        source="option",
        pid=42,
        alive=True,
    )
    assert agent.is_awaiting is True
    assert agent.is_running is False
