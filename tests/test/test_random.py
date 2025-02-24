"""Tests for libtmux's random test utilities."""

from __future__ import annotations

import string
import typing as t

import pytest

from libtmux.test.constants import TEST_SESSION_PREFIX
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


def test_random_str_sequence_doctest_examples() -> None:
    """Test the doctest examples for RandomStrSequence."""
    rng = RandomStrSequence()
    result1 = next(rng)
    result2 = next(rng)

    assert isinstance(result1, str)
    assert len(result1) == 8
    assert isinstance(result2, str)
    assert len(result2) == 8
    assert isinstance(next(rng), str)


def test_get_test_session_name_default_prefix(server: Server) -> None:
    """Test get_test_session_name with default prefix."""
    result = get_test_session_name(server=server)

    assert isinstance(result, str)
    assert result.startswith(TEST_SESSION_PREFIX)
    assert len(result) == len(TEST_SESSION_PREFIX) + 8  # prefix + random(8)
    assert not server.has_session(result)


def test_get_test_session_name_custom_prefix(server: Server) -> None:
    """Test get_test_session_name with custom prefix."""
    prefix = "test_"
    result = get_test_session_name(server=server, prefix=prefix)

    assert isinstance(result, str)
    assert result.startswith(prefix)
    assert len(result) == len(prefix) + 8  # prefix + random(8)
    assert not server.has_session(result)


def test_get_test_session_name_collision(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test get_test_session_name when first attempts collide."""
    collision_name = TEST_SESSION_PREFIX + "collision"
    success_name = TEST_SESSION_PREFIX + "success"
    name_iter = iter(["collision", "success"])

    def mock_next(self: t.Any) -> str:
        return next(name_iter)

    monkeypatch.setattr(RandomStrSequence, "__next__", mock_next)

    # Create a session that will cause a collision
    with server.new_session(collision_name):
        result = get_test_session_name(server=server)
        assert result == success_name
        assert not server.has_session(result)


def test_get_test_window_name_default_prefix(session: Session) -> None:
    """Test get_test_window_name with default prefix."""
    result = get_test_window_name(session=session)

    assert isinstance(result, str)
    assert result.startswith(TEST_SESSION_PREFIX)
    assert len(result) == len(TEST_SESSION_PREFIX) + 8  # prefix + random(8)
    assert not any(w.window_name == result for w in session.windows)


def test_get_test_window_name_custom_prefix(session: Session) -> None:
    """Test get_test_window_name with custom prefix."""
    prefix = "test_"
    result = get_test_window_name(session=session, prefix=prefix)

    assert isinstance(result, str)
    assert result.startswith(prefix)
    assert len(result) == len(prefix) + 8  # prefix + random(8)
    assert not any(w.window_name == result for w in session.windows)


def test_get_test_window_name_collision(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test get_test_window_name when first attempts collide."""
    collision_name = TEST_SESSION_PREFIX + "collision"
    success_name = TEST_SESSION_PREFIX + "success"
    name_iter = iter(["collision", "success"])

    def mock_next(self: t.Any) -> str:
        return next(name_iter)

    monkeypatch.setattr(RandomStrSequence, "__next__", mock_next)

    # Create a window that will cause a collision
    session.new_window(window_name=collision_name)
    result = get_test_window_name(session=session)
    assert result == success_name
    assert not any(w.window_name == result for w in session.windows)


def test_get_test_window_name_requires_prefix() -> None:
    """Test that get_test_window_name requires a prefix."""
    with pytest.raises(AssertionError):
        get_test_window_name(session=t.cast("Session", object()), prefix=None)
