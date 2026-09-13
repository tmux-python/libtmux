"""Tests for libtmux's testing utilities."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from libtmux import exc
from libtmux.test import retry


@dataclass
class Clock:
    """Advance retry time without relying on operating-system scheduling."""

    milliseconds: int = 0

    def time(self) -> float:
        """Return the controlled time in seconds."""
        return self.milliseconds / 1000

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
