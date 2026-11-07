"""Examples for working with multiple tmux servers.

This file contains examples of using the TestServer fixture to create
and manage multiple independent tmux server instances.
"""

from __future__ import annotations

import time


def test_basic_test_server(TestServer) -> None:
    """Test creating and using a server via TestServer fixture."""
    # TestServer returns a factory that creates servers with unique socket names
    server = TestServer()  # Create a server with a unique socket name

    # Create a session but we don't need to reference it
    server.new_session()
    assert server.is_alive()

    # Clean up is automatic at the end of the test


def test_with_config(TestServer, tmp_path) -> None:
    """Test creating a server with custom configuration."""
    # Create a custom tmux configuration in the temporary directory
    config_file = tmp_path / "tmux.conf"
    config_file.write_text("set -g status off")

    # Create a server using this configuration
    server = TestServer(config_file=str(config_file))

    # Start the server explicitly by creating a session
    server.new_session()

    # Give tmux a moment to start up
    time.sleep(0.5)

    # Verify the server is running
    assert server.is_alive()

    # Create a session to work with
    session = server.new_session(session_name="test_config")
    assert session.name == "test_config"

    # Clean up is automatic at the end of the test


def test_multiple_independent_servers(TestServer) -> None:
    """Test running multiple independent tmux servers simultaneously."""
    # Create first server
    server1 = TestServer()
    session1 = server1.new_session(session_name="session1")

    # Create second server (completely independent)
    server2 = TestServer()
    session2 = server2.new_session(session_name="session2")

    # Verify both servers are running
    assert server1.is_alive()
    assert server2.is_alive()

    # Verify sessions exist on their respective servers only
    assert session1.server is server1
    assert session2.server is server2

    # Verify session names are independent
    assert session1.name == "session1"
    assert session2.name == "session2"

    # Clean up is automatic at the end of the test
