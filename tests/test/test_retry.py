"""Tests for libtmux's testing utilities."""

from __future__ import annotations

from time import sleep, time

import pytest

from libtmux import exc
from libtmux.test.retry import retry_until


def test_retry_three_times() -> None:
    """Test retry_until()."""
    ini = time()
    value = 0

    def call_me_three_times() -> bool:
        nonlocal value
        sleep(0.3)  # Sleep for 0.3 seconds to simulate work

        if value == 2:
            return True

        value += 1
        return False

    retry_until(call_me_three_times, 1)

    end = time()

    assert 0.9 <= (end - ini) <= 1.1  # Allow for small timing variations


def test_function_times_out() -> None:
    """Test time outs with retry_until()."""
    ini = time()

    def never_true() -> bool:
        sleep(
            0.1,
        )  # Sleep for 0.1 seconds to simulate work (called ~10 times in 1 second)
        return False

    with pytest.raises(exc.WaitTimeout):
        retry_until(never_true, 1)

    end = time()

    assert 0.9 <= (end - ini) <= 1.1  # Allow for small timing variations


def test_function_times_out_no_raise() -> None:
    """Tests retry_until() with exception raising disabled."""
    ini = time()

    def never_true() -> bool:
        sleep(
            0.1,
        )  # Sleep for 0.1 seconds to simulate work (called ~10 times in 1 second)
        return False

    retry_until(never_true, 1, raises=False)

    end = time()
    assert 0.9 <= (end - ini) <= 1.1  # Allow for small timing variations


def test_function_times_out_no_raise_assert() -> None:
    """Tests retry_until() with exception raising disabled, returning False."""
    ini = time()

    def never_true() -> bool:
        sleep(
            0.1,
        )  # Sleep for 0.1 seconds to simulate work (called ~10 times in 1 second)
        return False

    assert not retry_until(never_true, 1, raises=False)

    end = time()
    assert 0.9 <= (end - ini) <= 1.1  # Allow for small timing variations


def test_retry_three_times_no_raise_assert() -> None:
    """Tests retry_until() with exception raising disabled, with closure variable."""
    ini = time()
    value = 0

    def call_me_three_times() -> bool:
        nonlocal value
        sleep(
            0.3,
        )  # Sleep for 0.3 seconds to simulate work (called 3 times in ~0.9 seconds)

        if value == 2:
            return True

        value += 1
        return False

    assert retry_until(call_me_three_times, 1, raises=False)

    end = time()
    assert 0.9 <= (end - ini) <= 1.1  # Allow for small timing variations
