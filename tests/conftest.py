"""Test-suite-wide fixtures for libtmux's own tests."""

from __future__ import annotations

import pytest

from libtmux.common import get_version, get_version_str

from ._aio import SpawnCounter


@pytest.fixture(autouse=True)
def _clear_get_version_cache() -> None:
    """Flush the tmux-version caches before each test.

    Several tests in test_common.py and legacy_api/test_common.py
    monkey-patch libtmux.common.tmux_cmd then call get_version() to
    assert parsed-version behavior. With memoization, a prior test's
    cached result would mask the mock — this fixture guarantees a fresh
    subprocess lookup per test. get_version and get_version_str cache
    independently, so flush both.
    """
    get_version.cache_clear()
    get_version_str.cache_clear()


@pytest.fixture
def spawns(monkeypatch: pytest.MonkeyPatch) -> SpawnCounter:
    """Spy on async client spawns, so a test waits for them instead of sleeping."""
    return SpawnCounter(monkeypatch)
