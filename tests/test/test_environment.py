"""Tests for libtmux's test environment utilities."""

from __future__ import annotations

import os

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
