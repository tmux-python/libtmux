"""Tests for the two agent-state signal parsers."""

from __future__ import annotations

from libtmux.experimental.agents.signals import OptionSignal, OscSignal, Reading
from libtmux.experimental.agents.state import AgentState


def test_option_signal_parses_subscription_changed() -> None:
    """Test parsing a valid subscription-changed notification."""
    line = "%subscription-changed agentstate $0 @0 1 %3 : running"
    reading = OptionSignal.parse(line)
    assert reading is not None
    assert reading.pane_id == "%3"
    assert reading.state is AgentState.RUNNING
    assert reading.source == "option"


def test_option_signal_ignores_other_notifications() -> None:
    """Test that non-subscription-changed notifications are ignored."""
    assert OptionSignal.parse("%output %1 hello") is None
    assert OptionSignal.parse("%window-add @3") is None


def test_osc_signal_reassembles_fragmented_bytes() -> None:
    """Test that OscSignal reassembles fragmented OSC escapes."""
    osc = OscSignal()
    # the probe proved %output arrives byte-fragmented; feed one byte at a time
    payload = b"\033]3008;state=awaiting_input\033\\"
    readings: list[Reading] = []
    for i in range(len(payload)):
        readings.extend(osc.feed("%2", payload[i : i + 1]))
    assert len(readings) == 1
    assert readings[0].pane_id == "%2"
    assert readings[0].state is AgentState.AWAITING_INPUT
    assert readings[0].source == "osc"
