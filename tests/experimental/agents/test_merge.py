"""Tests for latest-wins ordering."""

from __future__ import annotations

from libtmux.experimental.agents.merge import MonotonicCounter, Stamp, latest


def test_latest_prefers_higher_counter() -> None:
    """Test that latest() prefers higher counter values."""
    assert latest(Stamp(1, "option"), Stamp(2, "option")) is True
    assert latest(Stamp(2, "option"), Stamp(1, "option")) is False


def test_latest_tie_breaks_on_writer() -> None:
    """Test that latest() breaks ties using writer name in deterministic order."""
    # equal counters: deterministic tie-break, never a coin flip
    assert latest(Stamp(1, "option"), Stamp(1, "osc")) is True
    assert latest(Stamp(1, "osc"), Stamp(1, "option")) is False


def test_latest_accepts_first_value() -> None:
    """Test that latest() accepts incoming stamp when current is None."""
    assert latest(None, Stamp(0, "option")) is True


def test_monotonic_counter_strictly_increases() -> None:
    """Test that MonotonicCounter increments strictly by 1 each call."""
    clock = MonotonicCounter()
    assert [clock(), clock(), clock()] == [1, 2, 3]
