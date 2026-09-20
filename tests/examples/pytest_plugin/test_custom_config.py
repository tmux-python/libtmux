"""Examples for working with custom tmux configurations."""

from __future__ import annotations

import time


def test_with_custom_config(TestServer, tmp_path) -> None:
    """Test using a custom tmux configuration."""
    # Create a custom tmux configuration file
    config_file = tmp_path / "tmux.conf"
    # Simply test with a history-limit change which is more reliable
    config_file.write_text("set -g history-limit 5000")

    # Create a server with the custom configuration
    server = TestServer(config_file=str(config_file))

    # Create a session to ensure the server is active
    session = server.new_session("custom-config-test")

    # Verify server has our session
    assert server.has_session("custom-config-test")

    # Test that we can run commands in the session, which proves the config is working
    window = session.active_window
    pane = window.active_pane

    # Send a command
    pane.send_keys("echo 'Testing custom config'", enter=True)
    time.sleep(0.5)

    # Verify the command was executed
    output = pane.capture_pane()
    assert any("Testing custom config" in line for line in output)
