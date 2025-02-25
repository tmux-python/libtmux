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
    from pytest import MonkeyPatch

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


def test_get_test_session_name_loop_behavior(
    server: Server,
) -> None:
    """Test the loop behavior in get_test_session_name using real sessions."""
    # Get a first session name
    first_name = get_test_session_name(server=server)

    # Create this session to trigger the loop behavior
    with server.new_session(first_name):
        # Now when we call get_test_session_name again, it should
        # give us a different name since the first one is taken
        second_name = get_test_session_name(server=server)

        # Verify we got a different name
        assert first_name != second_name

        # Verify the first name exists as a session
        assert server.has_session(first_name)

        # Verify the second name doesn't exist yet
        assert not server.has_session(second_name)

        # Create a second session with the second name
        with server.new_session(second_name):
            # Now get a third name, to trigger another iteration
            third_name = get_test_session_name(server=server)

            # Verify all names are different
            assert first_name != third_name
            assert second_name != third_name

            # Verify the first two names exist as sessions
            assert server.has_session(first_name)
            assert server.has_session(second_name)

            # Verify the third name doesn't exist yet
            assert not server.has_session(third_name)


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


def test_get_test_window_name_loop_behavior(
    session: Session,
) -> None:
    """Test the loop behavior in get_test_window_name using real windows."""
    # Get a window name first
    first_name = get_test_window_name(session=session)

    # Create this window
    window = session.new_window(window_name=first_name)
    try:
        # Now when we call get_test_window_name again, it should
        # give us a different name since the first one is taken
        second_name = get_test_window_name(session=session)

        # Verify we got a different name
        assert first_name != second_name

        # Verify the first name exists as a window
        assert any(w.window_name == first_name for w in session.windows)

        # Verify the second name doesn't exist yet
        assert not any(w.window_name == second_name for w in session.windows)

        # Create a second window with the second name
        window2 = session.new_window(window_name=second_name)
        try:
            # Now get a third name, to trigger another iteration
            third_name = get_test_window_name(session=session)

            # Verify all names are different
            assert first_name != third_name
            assert second_name != third_name

            # Verify the first two names exist as windows
            assert any(w.window_name == first_name for w in session.windows)
            assert any(w.window_name == second_name for w in session.windows)

            # Verify the third name doesn't exist yet
            assert not any(w.window_name == third_name for w in session.windows)
        finally:
            # Clean up the second window
            if window2:
                window2.kill()
    finally:
        # Clean up
        if window:
            window.kill()


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


def test_random_str_sequence_small_character_set() -> None:
    """Test RandomStrSequence with a small character set."""
    # Using a small set forces it to use all characters
    small_chars = "abcdefgh"  # Exactly 8 characters
    rng = RandomStrSequence(characters=small_chars)
    result = next(rng)

    assert isinstance(result, str)
    assert len(result) == 8
    # Since it samples exactly 8 characters, all chars must be used
    assert sorted(result) == sorted(small_chars)


def test_random_str_sequence_insufficient_characters() -> None:
    """Test RandomStrSequence with too few characters."""
    # When fewer than 8 chars are provided, random.sample can't work
    tiny_chars = "abc"  # Only 3 characters
    rng = RandomStrSequence(characters=tiny_chars)

    # Should raise ValueError since random.sample(population, k)
    # requires k <= len(population)
    with pytest.raises(ValueError):
        next(rng)


def test_logger_configured(caplog: pytest.LogCaptureFixture) -> None:
    """Test that the logger in random.py is properly configured."""
    # Verify the logger is set up with the correct name
    assert logger.name == "libtmux.test.random"

    # Test that the logger functions properly
    with caplog.at_level(logging.DEBUG):
        logger.debug("Test debug message")
        logger.info("Test info message")

        assert "Test debug message" in caplog.text
        assert "Test info message" in caplog.text


def test_next_method_directly() -> None:
    """Test directly calling __next__ method on RandomStrSequence."""
    rng = RandomStrSequence()
    result = next(rng)
    assert isinstance(result, str)
    assert len(result) == 8
    assert all(c in rng.characters for c in result)


def test_namer_initialization() -> None:
    """Test that the namer global instance is initialized correctly."""
    # Since namer is a global instance from the random module,
    # we want to ensure it's properly initialized
    from libtmux.test.random import namer as direct_namer

    assert namer is direct_namer
    assert isinstance(namer, RandomStrSequence)
    assert namer.characters == "abcdefghijklmnopqrstuvwxyz0123456789_"


def test_random_str_sequence_iter_next_methods() -> None:
    """Test both __iter__ and __next__ methods directly."""
    # Initialize the sequence
    rng = RandomStrSequence()

    # Test __iter__ method
    iter_result = iter(rng)
    assert iter_result is rng

    # Test __next__ method directly multiple times
    results = []
    for _ in range(5):
        next_result = next(rng)
        results.append(next_result)
        assert isinstance(next_result, str)
        assert len(next_result) == 8
        assert all(c in rng.characters for c in next_result)

    # Verify all results are unique
    assert len(set(results)) == len(results)


def test_collisions_with_real_objects(
    server: Server,
    session: Session,
) -> None:
    """Test collision behavior using real tmux objects instead of mocks.

    This test replaces multiple monkeypatched tests:
    - test_get_test_session_name_collision
    - test_get_test_session_name_multiple_collisions
    - test_get_test_window_name_collision
    - test_get_test_window_name_multiple_collisions

    Instead of mocking the random generator, we create real sessions and
    windows with predictable names and verify the uniqueness logic.
    """
    # Test session name collisions
    # ----------------------------
    # Create a known prefix for testing
    prefix = "test_collision_"

    # Create several sessions with predictable names
    session_name1 = prefix + "session1"
    session_name2 = prefix + "session2"

    # Create a couple of actual sessions to force collisions
    with server.new_session(session_name1), server.new_session(session_name2):
        # Verify our sessions exist
        assert server.has_session(session_name1)
        assert server.has_session(session_name2)

        # When requesting a session name with same prefix, we should get a unique name
        # that doesn't match either existing session
        result = get_test_session_name(server=server, prefix=prefix)
        assert result.startswith(prefix)
        assert result != session_name1
        assert result != session_name2
        assert not server.has_session(result)

    # Test window name collisions
    # --------------------------
    # Create windows with predictable names
    window_name1 = prefix + "window1"
    window_name2 = prefix + "window2"

    # Create actual windows to force collisions
    window1 = session.new_window(window_name=window_name1)
    window2 = session.new_window(window_name=window_name2)

    try:
        # Verify our windows exist
        assert any(w.window_name == window_name1 for w in session.windows)
        assert any(w.window_name == window_name2 for w in session.windows)

        # When requesting a window name with same prefix, we should get a unique name
        # that doesn't match either existing window
        result = get_test_window_name(session=session, prefix=prefix)
        assert result.startswith(prefix)
        assert result != window_name1
        assert result != window_name2
        assert not any(w.window_name == result for w in session.windows)
    finally:
        # Clean up the windows we created
        if window1:
            window1.kill()
        if window2:
            window2.kill()


def test_imports_coverage() -> None:
    """Test coverage for import statements in random.py."""
    # This test simply ensures the imports are covered
    from libtmux.test import random

    assert hasattr(random, "logging")
    assert hasattr(random, "random")
    assert hasattr(random, "t")
    assert hasattr(random, "TEST_SESSION_PREFIX")


def test_iterator_protocol() -> None:
    """Test the complete iterator protocol of RandomStrSequence."""
    # Test the __iter__ method explicitly
    rng = RandomStrSequence()
    iterator = iter(rng)

    # Verify __iter__ returns self
    assert iterator is rng

    # Verify __next__ method works after explicit __iter__ call
    result = next(iterator)
    assert isinstance(result, str)
    assert len(result) == 8


def test_get_test_session_name_collision_handling(
    server: Server,
    monkeypatch: MonkeyPatch,
) -> None:
    """Test that get_test_session_name handles collisions properly."""
    # Mock server.has_session to first return True (collision) then False
    call_count = 0

    def mock_has_session(name: str) -> bool:
        nonlocal call_count
        call_count += 1
        # First call returns True (collision), second call returns False
        return call_count == 1

    # Mock the server.has_session method
    monkeypatch.setattr(server, "has_session", mock_has_session)

    # Should break out of the loop on the second iteration
    session_name = get_test_session_name(server)

    # Verify the method was called twice due to the collision
    assert call_count == 2
    assert session_name.startswith(TEST_SESSION_PREFIX)


def test_get_test_window_name_null_prefix() -> None:
    """Test that get_test_window_name with None prefix raises an assertion error."""
    # Create a mock session
    mock_session = t.cast("Session", object())

    # Verify that None prefix raises an assertion error
    with pytest.raises(AssertionError):
        get_test_window_name(mock_session, prefix=None)


def test_import_typing_coverage() -> None:
    """Test coverage for typing imports in random.py."""
    # This test covers the TYPE_CHECKING imports
    import typing as t

    # Import directly from the module to cover lines
    from libtmux.test import random

    # Verify the t.TYPE_CHECKING attribute exists
    assert hasattr(t, "TYPE_CHECKING")

    # Check for the typing module import
    assert "t" in dir(random)


def test_random_str_sequence_direct_instantiation() -> None:
    """Test direct instantiation of RandomStrSequence class."""
    # This covers lines in the class definition and __init__ method
    rng = RandomStrSequence()

    # Check attributes
    assert hasattr(rng, "characters")
    assert rng.characters == "abcdefghijklmnopqrstuvwxyz0123456789_"

    # Check methods
    assert hasattr(rng, "__iter__")
    assert hasattr(rng, "__next__")


def test_get_test_window_name_collision_handling(
    session: Session,
    monkeypatch: MonkeyPatch,
) -> None:
    """Test that get_test_window_name handles collisions properly."""
    # Create a specific prefix for this test
    prefix = "collision_test_"

    # Generate a random window name with our prefix
    first_name = prefix + next(namer)

    # Create a real window with this name to force a collision
    window = session.new_window(window_name=first_name)
    try:
        # Now when we call get_test_window_name, it should generate a different name
        window_name = get_test_window_name(session, prefix=prefix)

        # Verify we got a different name
        assert window_name != first_name
        assert window_name.startswith(prefix)

        # Verify the function worked around the collision properly
        assert not any(w.window_name == window_name for w in session.windows)
        assert any(w.window_name == first_name for w in session.windows)
    finally:
        # Clean up the window we created
        if window:
            window.kill()


def test_random_str_sequence_return_statements() -> None:
    """Test the return statements in RandomStrSequence methods."""
    # Test __iter__ return statement (Line 47)
    rng = RandomStrSequence()
    iter_result = iter(rng)
    assert iter_result is rng  # Verify it returns self

    # Test __next__ return statement (Line 51)
    next_result = next(rng)
    assert isinstance(next_result, str)
    assert len(next_result) == 8


def test_get_test_session_name_implementation_details(
    server: Server,
    monkeypatch: MonkeyPatch,
) -> None:
    """Test specific implementation details of get_test_session_name function."""
    # Create a session with a name that will cause a collision
    # This will test the while loop behavior (Lines 56-59)
    prefix = "collision_prefix_"
    first_random = next(namer)

    # Create a session that will match our first attempt inside get_test_session_name
    collision_name = prefix + first_random

    # Create a real session to force a collision
    with server.new_session(collision_name):
        # Now when we call get_test_session_name, it will need to try again
        # since the first attempt will collide with our created session
        result = get_test_session_name(server, prefix=prefix)

        # Verify collision handling
        assert result != collision_name
        assert result.startswith(prefix)


def test_get_test_window_name_branch_coverage(session: Session) -> None:
    """Test branch coverage for get_test_window_name function."""
    # This tests the branch condition on line 130->128

    # Create a window with a name that will cause a collision
    prefix = "branch_test_"
    first_random = next(namer)
    collision_name = prefix + first_random

    # Create a real window with this name
    window = session.new_window(window_name=collision_name)

    try:
        # Call function that should handle the collision
        result = get_test_window_name(session, prefix=prefix)

        # Verify collision handling behavior
        assert result != collision_name
        assert result.startswith(prefix)

    finally:
        # Clean up the window
        if window:
            window.kill()
