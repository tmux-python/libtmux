"""Tests for libtmux's testing utilities."""
from time import time

import pytest

from libtmux.exc import WaitTimeout
from libtmux.test import retry_until


def test_retry_three_times() -> None:
    """Test retry_until()."""
    ini = time()
    value = 0

    def call_me_three_times() -> bool:
        nonlocal value

        if value == 2:
            return True

        value += 1

        return False

    retry_until(call_me_three_times, 1)

    end = time()

    assert abs((end - ini) - 0.1) < 0.01


def test_function_times_out() -> None:
    """Test time outs with retry_until()."""
    ini = time()

    def never_true() -> bool:
        return False

    with pytest.raises(WaitTimeout):
        retry_until(never_true, 1)

    end = time()

    assert abs((end - ini) - 1.0) < 0.01


def test_function_times_out_no_raise() -> None:
    """Tests retry_until() with exception raising disabled."""
    ini = time()

    def never_true() -> bool:
        return False

    retry_until(never_true, 1, raises=False)

    end = time()

    assert abs((end - ini) - 1.0) < 0.01


def test_function_times_out_no_raise_assert() -> None:
    """Tests retry_until() with exception raising disabled, returning False."""
    ini = time()

    def never_true() -> bool:
        return False

    assert not retry_until(never_true, 1, raises=False)

    end = time()

    assert abs((end - ini) - 1.0) < 0.01


def test_retry_three_times_no_raise_assert() -> None:
    """Tests retry_until() with exception raising disabled, with closure variable."""
    ini = time()
    value = 0

    def call_me_three_times() -> bool:
        nonlocal value

        if value == 2:
            return True

        value += 1

        return False

    assert retry_until(call_me_three_times, 1, raises=False)

    end = time()

    assert abs((end - ini) - 0.1) < 0.01
