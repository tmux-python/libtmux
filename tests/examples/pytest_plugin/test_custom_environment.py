"""Examples for working with custom environment in tmux tests."""

from __future__ import annotations

import os
import time


def test_environment_variables(session) -> None:
    """Test setting and using environment variables."""
    # Create a window for testing
    window = session.new_window(window_name="env-test")
    pane = window.active_pane

    # Set environment variables for the pane
    test_env = {
        "TEST_VAR1": "value1",
        "TEST_VAR2": "value2",
        "TEST_PATH": "/custom/path:/another/path",
    }

    # Clear the pane first
    pane.send_keys("clear", enter=True)
    time.sleep(0.3)

    # Set environment variables
    for key, value in test_env.items():
        pane.send_keys(f"export {key}='{value}'", enter=True)

    time.sleep(0.5)

    # Verify environment variables were set
    pane.send_keys("echo $TEST_VAR1", enter=True)
    time.sleep(0.5)
    output = pane.capture_pane()
    assert any("value1" in line for line in output)

    # Test with a script that uses the variables
    pane.send_keys('echo "Combined: $TEST_VAR1 and $TEST_VAR2"', enter=True)
    time.sleep(0.5)
    output = pane.capture_pane()
    assert any("Combined: value1 and value2" in line for line in output)


def test_directory_navigation(session, tmp_path) -> None:
    """Test navigating directories in tmux."""
    # Create a window for testing
    window = session.new_window(window_name="dir-test")
    pane = window.active_pane

    # Clear the pane
    pane.send_keys("clear", enter=True)
    time.sleep(0.3)

    # Get and save the initial directory to tmp_path
    initial_dir_file = tmp_path / "initial_dir.txt"
    pane.send_keys(f"pwd > {initial_dir_file}", enter=True)
    time.sleep(0.5)

    # Navigate to /tmp directory
    pane.send_keys("cd /tmp", enter=True)
    time.sleep(0.5)

    # Verify we changed directory
    pane.send_keys("pwd", enter=True)
    time.sleep(0.5)
    output = pane.capture_pane()
    assert any("/tmp" in line for line in output)

    # Create a test directory and navigate to it
    test_dir = f"tmux_test_{os.getpid()}"
    pane.send_keys(f"mkdir -p {test_dir}", enter=True)
    pane.send_keys(f"cd {test_dir}", enter=True)
    time.sleep(0.5)

    # Verify we're in the test directory
    pane.send_keys("pwd", enter=True)
    time.sleep(0.5)
    output = pane.capture_pane()
    assert any(f"/tmp/{test_dir}" in line for line in output)

    # Clean up
    pane.send_keys("cd ..", enter=True)
    pane.send_keys(f"rm -r {test_dir}", enter=True)


def test_custom_session(TestServer) -> None:
    """Test creating a session with custom parameters."""
    # Create a new server instance
    server = TestServer()

    # Create a session with custom parameters
    session_params = {
        "session_name": "custom-session",
        "x": 800,
        "y": 600,
        "start_directory": "/tmp",
    }

    session = server.new_session(**session_params)

    # Verify session was created with the right name
    assert session.session_name == "custom-session"

    # Verify working directory was set correctly
    window = session.active_window
    pane = window.active_pane

    pane.send_keys("pwd", enter=True)
    time.sleep(0.5)
    output = pane.capture_pane()
    assert any("/tmp" in line for line in output)
