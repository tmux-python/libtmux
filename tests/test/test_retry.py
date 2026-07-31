"""Tests for libtmux's testing utilities."""

from __future__ import annotations

import typing as t
from time import monotonic, sleep

import pytest

from libtmux import exc
from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    from libtmux.session import Session


def test_retry_three_times() -> None:
    """Test retry_until()."""
    ini = monotonic()
    value = 0

    def call_me_three_times() -> bool:
        nonlocal value
        sleep(0.3)  # Sleep for 0.3 seconds to simulate work

        if value == 2:
            return True

        value += 1
        return False

    retry_until(call_me_three_times, 1)

    end = monotonic()

    assert 0.9 <= (end - ini) <= 1.1  # Allow for small timing variations


def test_function_times_out() -> None:
    """Test time outs with retry_until()."""
    ini = monotonic()

    def never_true() -> bool:
        sleep(
            0.1,
        )  # Sleep for 0.1 seconds to simulate work (called ~10 times in 1 second)
        return False

    with pytest.raises(exc.WaitTimeout):
        retry_until(never_true, 1)

    end = monotonic()

    assert 0.9 <= (end - ini) <= 1.1  # Allow for small timing variations


def test_function_times_out_no_raise() -> None:
    """Tests retry_until() with exception raising disabled."""
    ini = monotonic()

    def never_true() -> bool:
        sleep(
            0.1,
        )  # Sleep for 0.1 seconds to simulate work (called ~10 times in 1 second)
        return False

    retry_until(never_true, 1, raises=False)

    end = monotonic()
    assert 0.9 <= (end - ini) <= 1.1  # Allow for small timing variations


def test_function_times_out_no_raise_assert() -> None:
    """Tests retry_until() with exception raising disabled, returning False."""
    ini = monotonic()

    def never_true() -> bool:
        sleep(
            0.1,
        )  # Sleep for 0.1 seconds to simulate work (called ~10 times in 1 second)
        return False

    assert not retry_until(never_true, 1, raises=False)

    end = monotonic()
    assert 0.9 <= (end - ini) <= 1.1  # Allow for small timing variations


def test_retry_three_times_no_raise_assert() -> None:
    """Tests retry_until() with exception raising disabled, with closure variable."""
    ini = monotonic()
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

    end = monotonic()
    assert 0.9 <= (end - ini) <= 1.1  # Allow for small timing variations


def test_retry_until_forwards_args_from_loop(session: Session) -> None:
    """Waiting on a loop variable needs no closure, so no B023 suppression."""
    window = session.new_window(window_name="retry_until_args")
    active_pane = window.active_pane
    assert active_pane is not None
    panes = [active_pane, window.split()]

    for pane in panes:
        pane.send_keys("echo ready")

    for pane in panes:
        # Whole lines, not a substring: capture_pane returns the command tmux
        # echoed onto the pane, so ``"ready" in ...`` is true before the shell
        # has run and the wait would prove nothing.
        assert retry_until(
            lambda p: any(line.strip() == "ready" for line in p.capture_pane()),
            2,
            args=(pane,),
        )


def test_retry_until_args_reach_predicate() -> None:
    """Every retry passes the same ``args`` to the predicate."""
    seen: list[tuple[str, int]] = []

    def ready(name: str, threshold: int) -> bool:
        seen.append((name, threshold))
        return len(seen) >= threshold

    assert retry_until(ready, 1, args=("pane", 3), interval=0)
    assert seen == [("pane", 3)] * 3


def test_wall_clock_step_does_not_end_the_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wall-clock jump mid-wait neither shortens nor lengthens the budget.

    Regression: the budget was measured with :func:`time.time`, so an NTP
    correction, a container clock sync, or a VM resume landing inside the
    wait ended it early. Stepping :func:`time.time` forward by an hour here
    must not be observable, because nothing reads it.
    """
    stepped = 0.0

    def stepping_time() -> float:
        nonlocal stepped
        stepped += 3600.0
        return monotonic() + stepped

    monkeypatch.setattr("time.time", stepping_time)

    calls = 0

    def true_on_third() -> bool:
        nonlocal calls
        calls += 1
        return calls >= 3

    assert retry_until(true_on_third, 5)
    assert calls == 3
