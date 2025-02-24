"""Tests for libtmux's random test utilities."""

from __future__ import annotations

import string
import typing as t

import pytest

from libtmux.test.random import (
    RandomStrSequence,
    get_test_session_name,
    get_test_window_name,
)

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session


def test_random_str_sequence_default() -> None:
    """Test RandomStrSequence with default characters."""
    rng = RandomStrSequence()
    result = next(rng)

    assert isinstance(result, str)
    assert len(result) == 8
    assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in result)


def test_random_str_sequence_custom_chars() -> None:
    """Test RandomStrSequence with custom characters."""
    custom_chars = string.ascii_uppercase  # Enough characters for sampling
    rng = RandomStrSequence(characters=custom_chars)
    result = next(rng)

    assert isinstance(result, str)
    assert len(result) == 8
    assert all(c in custom_chars for c in result)


def test_random_str_sequence_uniqueness() -> None:
    """Test that RandomStrSequence generates unique strings."""
    rng = RandomStrSequence()
    results = [next(rng) for _ in range(100)]

    # Check uniqueness
    assert len(set(results)) == len(results)


def test_random_str_sequence_iterator() -> None:
    """Test that RandomStrSequence is a proper iterator."""
    rng = RandomStrSequence()
    assert iter(rng) is rng


def test_get_test_session_name(server: Server) -> None:
    """Test get_test_session_name function."""
    result = get_test_session_name(server=server)

    assert isinstance(result, str)
    assert result.startswith("libtmux_")  # Uses TEST_SESSION_PREFIX
    assert len(result) == 16  # prefix(8) + random(8)
    assert not server.has_session(result)


def test_get_test_window_name(session: Session) -> None:
    """Test get_test_window_name function."""
    result = get_test_window_name(session=session)

    assert isinstance(result, str)
    assert result.startswith("libtmux_")  # Uses TEST_SESSION_PREFIX
    assert len(result) == 16  # prefix(8) + random(8)
    assert not any(w.window_name == result for w in session.windows)


def test_get_test_window_name_requires_prefix() -> None:
    """Test that get_test_window_name requires a prefix."""
    with pytest.raises(AssertionError):
        get_test_window_name(session=t.cast("Session", object()), prefix=None)
