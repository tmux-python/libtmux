"""Tests for libtmux's testing utilities."""

from __future__ import annotations

import types
import typing as t

import pytest

from libtmux import exc
from libtmux.test import retry as retry_module
from libtmux.test.retry import retry_until


class FakeClock:
    """Deterministic stand-in for the ``time`` module used by ``retry_until``.

    ``sleep`` advances ``monotonic`` instead of waiting, so elapsed time is
    exact however loaded the machine is. It defines no ``time`` attribute:
    ``retry_until`` must measure with the monotonic clock, which a wall-clock
    step cannot move backwards.
    """

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        """Return the fake clock's current reading."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Advance the fake clock without waiting."""
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    """Replace the ``time`` module inside ``retry_until`` with a fake clock."""
    fake = FakeClock()
    monkeypatch.setattr(
        retry_module,
        "time",
        t.cast("types.ModuleType", fake),
    )
    return fake


def test_retry_three_times(clock: FakeClock) -> None:
    """Test retry_until()."""
    value = 0

    def call_me_three_times() -> bool:
        nonlocal value
        clock.sleep(0.3)  # simulate work

        if value == 2:
            return True

        value += 1
        return False

    retry_until(call_me_three_times, 1)

    # three calls of 0.3s work, two 0.05s default intervals between them
    assert clock.now == pytest.approx(1.0)


def test_function_times_out(clock: FakeClock) -> None:
    """Test time outs with retry_until()."""

    def never_true() -> bool:
        clock.sleep(0.1)  # simulate work
        return False

    with pytest.raises(exc.WaitTimeout):
        retry_until(never_true, 1)

    assert 1.0 <= clock.now <= 1.1


def test_function_times_out_no_raise(clock: FakeClock) -> None:
    """Tests retry_until() with exception raising disabled."""

    def never_true() -> bool:
        clock.sleep(0.1)  # simulate work
        return False

    retry_until(never_true, 1, raises=False)

    assert 1.0 <= clock.now <= 1.1


def test_function_times_out_no_raise_assert(clock: FakeClock) -> None:
    """Tests retry_until() with exception raising disabled, returning False."""

    def never_true() -> bool:
        clock.sleep(0.1)  # simulate work
        return False

    assert not retry_until(never_true, 1, raises=False)

    assert 1.0 <= clock.now <= 1.1


def test_retry_three_times_no_raise_assert(clock: FakeClock) -> None:
    """Tests retry_until() with exception raising disabled, with closure variable."""
    value = 0

    def call_me_three_times() -> bool:
        nonlocal value
        clock.sleep(0.3)  # simulate work

        if value == 2:
            return True

        value += 1
        return False

    assert retry_until(call_me_three_times, 1, raises=False)

    assert clock.now == pytest.approx(1.0)
