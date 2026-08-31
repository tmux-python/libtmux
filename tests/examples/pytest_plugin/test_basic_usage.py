"""Basic usage examples for the libtmux pytest plugin."""

from __future__ import annotations

import time


def test_basic_server(server, session) -> None:
    """Test basic server connection.

    Note: We need a session fixture to ensure there's an active session.
    """
    # Verify the server has sessions by checking for the session provided by the fixture
    sessions = server.sessions
    assert sessions, "Server should have at least one session"

    # Check if the server is responding to commands
    assert server.cmd("list-sessions").stdout is not None


def test_basic_session(session) -> None:
    """Test basic session functionality."""
    # Session should be created by the fixture
    assert session is not None

    # Session should have a name
    assert session.session_name

    # Get session info
    session_info = session.cmd("display-message", "-p", "#{session_name}").stdout
    assert len(session_info) > 0


def test_basic_window(session) -> None:
    """Test basic window creation."""
    # Create a new window
    window = session.new_window(window_name="test-window")

    # Verify window was created with the correct name
    assert window.window_name == "test-window"

    # Get the number of panes in the window
    assert len(window.panes) == 1

    # Rename the window
    window.rename_window("renamed-window")
    assert window.window_name == "renamed-window"


def test_basic_pane(session) -> None:
    """Test basic pane functionality."""
    window = session.new_window(window_name="pane-test")
    pane = window.active_pane

    # Send a command to the pane
    pane.send_keys("echo 'Hello, tmux!'", enter=True)

    # Give the command time to execute
    time.sleep(0.5)

    # Capture the pane output
    output = pane.capture_pane()

    # Verify the output contains our message
    assert any("Hello, tmux!" in line for line in output)
