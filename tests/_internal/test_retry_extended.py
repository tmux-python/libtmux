"""Tests for retry_until_extended function."""

from __future__ import annotations

import pytest

from libtmux._internal.retry_extended import retry_until_extended
from libtmux.exc import WaitTimeout


def test_retry_success_immediate() -> None:
    """Test function returns True immediately on first call."""
    call_count = 0

    def always_true() -> bool:
        nonlocal call_count
        call_count += 1
        return True

    success, exception = retry_until_extended(always_true, seconds=1.0)

    assert success is True
    assert exception is None
    assert call_count == 1


def test_retry_success_after_attempts() -> None:
    """Test function succeeds after a few retries."""
    call_count = 0

    def succeeds_on_third() -> bool:
        nonlocal call_count
        call_count += 1
        return call_count >= 3

    success, exception = retry_until_extended(
        succeeds_on_third,
        seconds=2.0,
        interval=0.01,
    )

    assert success is True
    assert exception is None
    assert call_count == 3


def test_retry_timeout_raises() -> None:
    """Test timeout raises WaitTimeout when raises=True."""
    with pytest.raises(WaitTimeout, match="Timed out after"):
        retry_until_extended(
            lambda: False,
            seconds=0.05,
            interval=0.01,
            raises=True,
        )


def test_retry_timeout_no_raise() -> None:
    """Test timeout returns (False, WaitTimeout) when raises=False."""
    success, exception = retry_until_extended(
        lambda: False,
        seconds=0.05,
        interval=0.01,
        raises=False,
    )

    assert success is False
    assert isinstance(exception, WaitTimeout)
    assert "Timed out after" in str(exception)
