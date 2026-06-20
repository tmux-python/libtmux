"""Tests for libtmux's testing utilities."""

from __future__ import annotations

from time import sleep, time

import pytest

from libtmux import exc
from libtmux.test.retry import retry_until


def test_retry_three_times() -> None:
    """retry_until retries until the callable succeeds."""
    calls = 0
    value = 0

    def call_me_three_times() -> bool:
        nonlocal value, calls
        calls += 1
        sleep(0.3)  # simulate work

        if value == 2:
            return True

        value += 1
        return False

    # Generous budget so all three calls fit even under load; assert on behavior
    # (call count + success), not wall-clock, to stay deterministic.
    assert retry_until(call_me_three_times, 5) is True
    assert calls == 3


def test_function_times_out() -> None:
    """retry_until raises WaitTimeout after exhausting its budget."""
    ini = time()
    calls = 0

    def never_true() -> bool:
        nonlocal calls
        calls += 1
        sleep(0.1)  # simulate work
        return False

    with pytest.raises(exc.WaitTimeout):
        retry_until(never_true, 1)

    # It retried for the full budget before timing out. The lower bound is
    # deterministic (retry_until only times out once elapsed >= the budget);
    # no fragile upper bound that load can blow past.
    assert (time() - ini) >= 0.9
    assert calls > 1


def test_function_times_out_no_raise() -> None:
    """retry_until returns instead of raising when raises=False."""
    ini = time()
    calls = 0

    def never_true() -> bool:
        nonlocal calls
        calls += 1
        sleep(0.1)  # simulate work
        return False

    retry_until(never_true, 1, raises=False)

    assert (time() - ini) >= 0.9
    assert calls > 1


def test_function_times_out_no_raise_assert() -> None:
    """retry_until returns False on timeout when raises=False."""
    ini = time()
    calls = 0

    def never_true() -> bool:
        nonlocal calls
        calls += 1
        sleep(0.1)  # simulate work
        return False

    assert not retry_until(never_true, 1, raises=False)

    assert (time() - ini) >= 0.9
    assert calls > 1


def test_retry_three_times_no_raise_assert() -> None:
    """retry_until returns True on success even with raises=False."""
    calls = 0
    value = 0

    def call_me_three_times() -> bool:
        nonlocal value, calls
        calls += 1
        sleep(0.3)  # simulate work

        if value == 2:
            return True

        value += 1
        return False

    # Behavior-based, generous budget: deterministic even under load.
    assert retry_until(call_me_three_times, 5, raises=False) is True
    assert calls == 3
