"""Tests for libtmux's testing utilities."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass
from time import monotonic

import pytest

from libtmux import exc
from libtmux.test import retry
from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    from libtmux.session import Session


@dataclass
class Clock:
    """Advance retry time without relying on operating-system scheduling."""

    milliseconds: int = 0

    def time(self) -> float:
        """Return the controlled time in seconds."""
        return self.milliseconds / 1000

    def monotonic(self) -> float:
        """Return the controlled time in seconds; retry_until reads this clock."""
        return self.time()

    def sleep(self, seconds: float) -> None:
        """Advance time without blocking the test."""
        self.milliseconds += round(seconds * 1000)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    """Replace only the retry module's clock, leaving pytest's clock intact."""
    controlled = Clock()
    monkeypatch.setattr(retry, "time", controlled)
    return controlled


@pytest.mark.parametrize("raises", [True, False])
def test_retry_three_times(clock: Clock, raises: bool) -> None:
    """Return success after two false results and the configured intervals."""
    attempts = 0

    def eventually_true() -> bool:
        nonlocal attempts
        clock.sleep(0.3)
        attempts += 1
        return attempts == 3

    assert retry.retry_until(eventually_true, 1, raises=raises)
    assert attempts == 3
    assert clock.time() == 1


@pytest.mark.parametrize("raises", [True, False, None])
def test_function_times_out(clock: Clock, raises: bool | None) -> None:
    """Stop retrying at the deadline through the selected failure channel."""
    attempts = 0

    def never_true() -> bool:
        nonlocal attempts
        clock.sleep(0.1)
        attempts += 1
        return False

    if raises:
        with pytest.raises(exc.WaitTimeout):
            retry.retry_until(never_true, 1, raises=raises)
    else:
        assert not retry.retry_until(never_true, 1, raises=raises)

    assert attempts == 7
    assert clock.time() == 1


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
