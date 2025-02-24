"""Tests for libtmux's random test utilities."""

from __future__ import annotations

import logging
import string
import sys
import typing as t

import pytest

from libtmux.test.constants import TEST_SESSION_PREFIX
from libtmux.test.random import (
    RandomStrSequence,
    get_test_session_name,
    get_test_window_name,
    logger,
    namer,
)

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session


def test_logger() -> None:
    """Test that the logger is properly configured."""
    assert isinstance(logger, logging.Logger)
    assert logger.name == "libtmux.test.random"


def test_random_str_sequence_default() -> None:
    """Test RandomStrSequence with default characters."""
    rng = RandomStrSequence()
    result = next(rng)

    assert isinstance(result, str)
    assert len(result) == 8
    assert all(c in rng.characters for c in result)


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


def test_namer_global_instance() -> None:
    """Test the global namer instance."""
    # Test that namer is an instance of RandomStrSequence
    assert isinstance(namer, RandomStrSequence)

    # Test that it generates valid strings
    result = next(namer)
    assert isinstance(result, str)
    assert len(result) == 8
    assert all(c in namer.characters for c in result)

    # Test uniqueness
    results = [next(namer) for _ in range(10)]
    assert len(set(results)) == len(results)


def test_get_test_session_name_doctest_examples(server: Server) -> None:
    """Test the doctest examples for get_test_session_name."""
    # Test basic functionality
    result = get_test_session_name(server=server)
    assert result.startswith(TEST_SESSION_PREFIX)
    assert len(result) == len(TEST_SESSION_PREFIX) + 8

    # Test uniqueness (from doctest example)
    result1 = get_test_session_name(server=server)
    result2 = get_test_session_name(server=server)
    assert result1 != result2


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


def test_get_test_session_name_multiple_collisions(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test get_test_session_name with multiple collisions."""
    names = ["collision1", "collision2", "success"]
    collision_names = [TEST_SESSION_PREFIX + name for name in names[:-1]]
    success_name = TEST_SESSION_PREFIX + names[-1]
    name_iter = iter(names)

    def mock_next(self: t.Any) -> str:
        return next(name_iter)

    monkeypatch.setattr(RandomStrSequence, "__next__", mock_next)

    # Create sessions that will cause collisions
    with server.new_session(collision_names[0]), server.new_session(collision_names[1]):
        result = get_test_session_name(server=server)
        assert result == success_name
        assert not server.has_session(result)


def test_get_test_window_name_doctest_examples(session: Session) -> None:
    """Test the doctest examples for get_test_window_name."""
    # Test basic functionality
    result = get_test_window_name(session=session)
    assert result.startswith(TEST_SESSION_PREFIX)
    assert len(result) == len(TEST_SESSION_PREFIX) + 8

    # Test uniqueness (from doctest example)
    result1 = get_test_window_name(session=session)
    result2 = get_test_window_name(session=session)
    assert result1 != result2


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


def test_get_test_window_name_multiple_collisions(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test get_test_window_name with multiple collisions."""
    names = ["collision1", "collision2", "success"]
    collision_names = [TEST_SESSION_PREFIX + name for name in names[:-1]]
    success_name = TEST_SESSION_PREFIX + names[-1]
    name_iter = iter(names)

    def mock_next(self: t.Any) -> str:
        return next(name_iter)

    monkeypatch.setattr(RandomStrSequence, "__next__", mock_next)

    # Create windows that will cause collisions
    for name in collision_names:
        session.new_window(window_name=name)

    result = get_test_window_name(session=session)
    assert result == success_name
    assert not any(w.window_name == result for w in session.windows)


def test_get_test_window_name_requires_prefix() -> None:
    """Test that get_test_window_name requires a prefix."""
    with pytest.raises(AssertionError):
        get_test_window_name(session=t.cast("Session", object()), prefix=None)


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="Self type only available in Python 3.11+",
)
def test_random_str_sequence_self_type() -> None:
    """Test that RandomStrSequence works with Self type annotation."""
    rng = RandomStrSequence()
    iter_result = iter(rng)
    assert isinstance(iter_result, RandomStrSequence)
    assert iter_result is rng
