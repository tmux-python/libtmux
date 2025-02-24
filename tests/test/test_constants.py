"""Tests for libtmux's test constants."""

from __future__ import annotations

from typing import TYPE_CHECKING

from libtmux.test.constants import (
    RETRY_INTERVAL_SECONDS,
    RETRY_TIMEOUT_SECONDS,
    TEST_SESSION_PREFIX,
)

if TYPE_CHECKING:
    import pytest


def test_test_session_prefix() -> None:
    """Test TEST_SESSION_PREFIX is correctly defined."""
    assert TEST_SESSION_PREFIX == "libtmux_"


def test_retry_timeout_seconds_default() -> None:
    """Test RETRY_TIMEOUT_SECONDS default value."""
    assert RETRY_TIMEOUT_SECONDS == 8


def test_retry_timeout_seconds_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test RETRY_TIMEOUT_SECONDS can be configured via environment variable."""
    monkeypatch.setenv("RETRY_TIMEOUT_SECONDS", "10")
    from importlib import reload

    import libtmux.test.constants

    reload(libtmux.test.constants)
    assert libtmux.test.constants.RETRY_TIMEOUT_SECONDS == 10


def test_retry_interval_seconds_default() -> None:
    """Test RETRY_INTERVAL_SECONDS default value."""
    assert RETRY_INTERVAL_SECONDS == 0.05


def test_retry_interval_seconds_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test RETRY_INTERVAL_SECONDS can be configured via environment variable."""
    monkeypatch.setenv("RETRY_INTERVAL_SECONDS", "0.1")
    from importlib import reload

    import libtmux.test.constants

    reload(libtmux.test.constants)
    assert libtmux.test.constants.RETRY_INTERVAL_SECONDS == 0.1
