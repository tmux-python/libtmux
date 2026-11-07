"""Examples of using test server configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from libtmux import Server


@pytest.fixture
def custom_config() -> dict[str, Any]:
    """Fixture providing custom configuration settings.

    Returns
    -------
    dict[str, Any]
        Configuration dictionary with tmux settings
    """
    return {
        "colors": 256,
        "default-terminal": "screen-256color",
        "history-limit": 5000,
    }


def test_server_config(server: Server, session: object) -> None:
    """Test server configuration."""
    # Create a session and verify it works
    # Note: The session fixture ensures we have an active session already
    assert session is not None

    # Get color configuration using tmux command
    colors = server.cmd("show-option", "-g", "default-terminal").stdout
    assert colors is not None


def test_server_operations(server: Server) -> None:
    """Test basic server operations."""
    # Create a new session for this test
    new_session = server.new_session(session_name="ops-test")
    assert new_session.name == "ops-test"

    # Create multiple windows
    windows = []
    expected_window_count = 3
    for i in range(expected_window_count):
        window = new_session.new_window(window_name=f"window-{i}")
        windows.append(window)

    # Verify windows were created
    assert len(new_session.windows) >= expected_window_count
    for i, window in enumerate(windows):
        assert f"window-{i}" == window.window_name
