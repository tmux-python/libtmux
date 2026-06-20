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
    ini = monotonic()
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
    assert (monotonic() - ini) >= 0.9
    assert calls > 1


def test_function_times_out_no_raise() -> None:
    """retry_until returns instead of raising when raises=False."""
    ini = monotonic()
    calls = 0

    def never_true() -> bool:
        nonlocal calls
        calls += 1
        sleep(0.1)  # simulate work
        return False

    retry_until(never_true, 1, raises=False)

    assert (monotonic() - ini) >= 0.9
    assert calls > 1


def test_function_times_out_no_raise_assert() -> None:
    """retry_until returns False on timeout when raises=False."""
    ini = monotonic()
    calls = 0

    def never_true() -> bool:
        nonlocal calls
        calls += 1
        sleep(0.1)  # simulate work
        return False

    assert not retry_until(never_true, 1, raises=False)

    assert (monotonic() - ini) >= 0.9
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
