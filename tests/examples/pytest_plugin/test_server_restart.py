"""Examples of testing across tmux server restarts."""

from __future__ import annotations

import os
import subprocess
import time
from typing import TYPE_CHECKING, cast

import libtmux

if TYPE_CHECKING:
    from libtmux.pane import Pane


def test_persist_across_restart(session) -> None:
    """Test functionality across server restarts."""
    # Set up initial state
    window = session.new_window(window_name="persist-test")
    pane = cast("Pane", window.active_pane)
    pane.send_keys("echo 'Data to persist' > /tmp/test-data.txt", enter=True)
    time.sleep(0.5)

    # Get server info for reconnecting
    socket_path = session.server.socket_path

    # Create a custom socket path for a new server, different from both
    # the main tmux server and the test server
    custom_socket = f"/tmp/custom-tmux-test-{os.getpid()}"

    # Create a new server with the custom socket
    custom_server = libtmux.Server(socket_path=custom_socket)
    try:
        # Create a new session on the custom server
        custom_session = custom_server.new_session(session_name="custom-test")

        # Verify our file still exists
        # Use cast to ensure mypy knows this is a Pane object
        custom_pane = cast("Pane", custom_session.active_window.active_pane)
        custom_pane.send_keys("cat /tmp/test-data.txt", enter=True)
        time.sleep(0.5)

        output = custom_pane.capture_pane()
        assert any("Data to persist" in line for line in output)
    finally:
        # Clean up only our custom server
        if "custom_server" in locals():
            custom_server.kill()

        # Remove the test file
        subprocess.run(["rm", "-f", "/tmp/test-data.txt"], check=False)
        # Also remove the custom socket if it still exists
        subprocess.run(["rm", "-f", custom_socket], check=False)
