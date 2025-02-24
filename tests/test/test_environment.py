"""Tests for libtmux's test environment utilities."""

from __future__ import annotations

import os
import typing as t

from libtmux.test.environment import EnvironmentVarGuard


def test_environment_var_guard_set() -> None:
    """Test setting environment variables with EnvironmentVarGuard."""
    env = EnvironmentVarGuard()

    # Test setting a new variable
    env.set("TEST_NEW_VAR", "new_value")
    assert os.environ["TEST_NEW_VAR"] == "new_value"

    # Test setting an existing variable
    os.environ["TEST_EXISTING_VAR"] = "original_value"
    env.set("TEST_EXISTING_VAR", "new_value")
    assert os.environ["TEST_EXISTING_VAR"] == "new_value"

    # Test cleanup
    env.__exit__(None, None, None)
    assert "TEST_NEW_VAR" not in os.environ
    assert os.environ["TEST_EXISTING_VAR"] == "original_value"


def test_environment_var_guard_unset() -> None:
    """Test unsetting environment variables with EnvironmentVarGuard."""
    env = EnvironmentVarGuard()

    # Test unsetting an existing variable
    os.environ["TEST_EXISTING_VAR"] = "original_value"
    env.unset("TEST_EXISTING_VAR")
    assert "TEST_EXISTING_VAR" not in os.environ

    # Test unsetting a non-existent variable (should not raise)
    env.unset("TEST_NON_EXISTENT_VAR")

    # Test cleanup
    env.__exit__(None, None, None)
    assert os.environ["TEST_EXISTING_VAR"] == "original_value"


def test_environment_var_guard_context_manager() -> None:
    """Test using EnvironmentVarGuard as a context manager."""
    os.environ["TEST_EXISTING_VAR"] = "original_value"

    with EnvironmentVarGuard() as env:
        # Set new and existing variables
        env.set("TEST_NEW_VAR", "new_value")
        env.set("TEST_EXISTING_VAR", "new_value")
        assert os.environ["TEST_NEW_VAR"] == "new_value"
        assert os.environ["TEST_EXISTING_VAR"] == "new_value"

        # Unset a variable
        env.unset("TEST_EXISTING_VAR")
        assert "TEST_EXISTING_VAR" not in os.environ

    # Test cleanup after context
    assert "TEST_NEW_VAR" not in os.environ
    assert os.environ["TEST_EXISTING_VAR"] == "original_value"


def test_environment_var_guard_cleanup_on_exception() -> None:
    """Test that EnvironmentVarGuard cleans up even when an exception occurs."""
    os.environ["TEST_EXISTING_VAR"] = "original_value"

    def _raise_error() -> None:
        raise RuntimeError

    try:
        with EnvironmentVarGuard() as env:
            env.set("TEST_NEW_VAR", "new_value")
            env.set("TEST_EXISTING_VAR", "new_value")
            _raise_error()
    except RuntimeError:
        pass

    # Test cleanup after exception
    assert "TEST_NEW_VAR" not in os.environ
    assert os.environ["TEST_EXISTING_VAR"] == "original_value"


def test_environment_var_guard_unset_and_reset() -> None:
    """Test unsetting and then resetting a variable."""
    env = EnvironmentVarGuard()

    # Set up test variables
    os.environ["TEST_VAR1"] = "value1"
    os.environ["TEST_VAR2"] = "value2"

    # Unset a variable
    env.unset("TEST_VAR1")
    assert "TEST_VAR1" not in os.environ

    # Set it again with a different value
    env.set("TEST_VAR1", "new_value1")
    assert os.environ["TEST_VAR1"] == "new_value1"

    # Unset a variable that was previously set in this context
    env.set("TEST_VAR2", "new_value2")
    env.unset("TEST_VAR2")
    assert "TEST_VAR2" not in os.environ

    # Cleanup
    env.__exit__(None, None, None)
    assert os.environ["TEST_VAR1"] == "value1"
    assert os.environ["TEST_VAR2"] == "value2"


def test_environment_var_guard_exit_with_exception() -> None:
    """Test __exit__ method with exception parameters."""
    env = EnvironmentVarGuard()

    # Set up test variables
    os.environ["TEST_VAR"] = "original_value"
    env.set("TEST_VAR", "new_value")

    # Call __exit__ with exception parameters
    env.__exit__(
        t.cast("type[BaseException]", RuntimeError),
        RuntimeError("Test exception"),
        None,
    )

    # Verify cleanup still happened
    assert os.environ["TEST_VAR"] == "original_value"


def test_environment_var_guard_unset_previously_set() -> None:
    """Test unsetting a variable that was previously set in the same context."""
    env = EnvironmentVarGuard()

    # Make sure the variable doesn't exist initially
    if "TEST_NEW_VAR" in os.environ:
        del os.environ["TEST_NEW_VAR"]

    # Set a new variable
    env.set("TEST_NEW_VAR", "new_value")
    assert "TEST_NEW_VAR" in os.environ
    assert os.environ["TEST_NEW_VAR"] == "new_value"

    # Now unset it - this should hit line 57
    env.unset("TEST_NEW_VAR")
    assert "TEST_NEW_VAR" not in os.environ

    # No need to check after cleanup since the variable was never in the environment
    # before we started
