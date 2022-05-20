from time import time

import pytest

from libtmux.test import WaitTimeout, retry_until


def test_retry_three_times():
    ini = time()
    value = 0

    def call_me_three_times():
        nonlocal value

        if value == 2:
            return True

        value += 1

        return False

    retry_until(call_me_three_times, 1)

    end = time()

    assert abs((end - ini) - 0.1) < 0.01


def test_function_times_out():
    ini = time()

    def never_true():
        return False

    with pytest.raises(WaitTimeout):
        retry_until(never_true, 1)

    end = time()

    assert abs((end - ini) - 1.0) < 0.01


def test_function_times_out_no_rise():
    ini = time()

    def never_true():
        return False

    retry_until(never_true, 1, raises=False)

    end = time()

    assert abs((end - ini) - 1.0) < 0.01


def test_function_times_out_no_raise_assert():
    ini = time()

    def never_true():
        return False

    assert not retry_until(never_true, 1, raises=False)

    end = time()

    assert abs((end - ini) - 1.0) < 0.01


def test_retry_three_times_no_raise_assert():
    ini = time()
    value = 0

    def call_me_three_times():
        nonlocal value

        if value == 2:
            return True

        value += 1

        return False

    assert retry_until(call_me_three_times, 1, raises=False)

    end = time()

    assert abs((end - ini) - 0.1) < 0.01
