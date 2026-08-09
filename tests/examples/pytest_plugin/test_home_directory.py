"""Examples for setting up a temporary home directory for tests.

This file demonstrates how to set up and use a temporary home directory
for tests, which is useful for isolating configuration files.
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import pathlib


@pytest.fixture(autouse=True)
def set_home(
    monkeypatch: pytest.MonkeyPatch,
    user_path: pathlib.Path,
) -> None:
    """Set the HOME environment variable to a temporary directory."""
    monkeypatch.setenv("HOME", str(user_path))


def test_home_directory_set(session) -> None:
    """Test that the HOME environment variable is set correctly."""
    # Get the active pane to run commands
    pane = session.active_window.active_pane

    # Execute a command to print the HOME directory
    pane.send_keys("echo $HOME", enter=True)

    # Wait for the command to execute
    time.sleep(1)

    # Capture the output
    output = pane.capture_pane()

    # Get what we expect the HOME to be
    expected_home = os.environ.get("HOME")
    assert expected_home, "HOME environment variable not set"

    # The output should include the HOME path somewhere
    found_home = False
    for line in output:
        if expected_home in line:
            found_home = True
            break

    assert found_home, f"Expected to find {expected_home} in output: {output}"


def test_create_config_in_home(session, user_path) -> None:
    """Test creating and using configuration in the temporary home directory."""
    # Create a simple configuration file in the home directory
    config_file = user_path / ".my-test-config"
    config_file.write_text("test-config-value")

    # Get the active pane to run commands
    pane = session.active_window.active_pane

    # Execute a command to check the config file exists
    pane.send_keys(f"cat {config_file}", enter=True)

    # Wait a moment for the command to execute
    time.sleep(1)

    # Capture and verify the output
    output = pane.capture_pane()
    assert any("test-config-value" in line for line in output), (
        "Config file content not found"
    )
