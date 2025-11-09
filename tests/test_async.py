"""Tests for libtmux async operations.

SAFETY: All tests use isolated test servers via fixtures.
Socket names: libtmux_test{8_random_chars} - never affects developer sessions.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import pytest

from libtmux.pane import Pane
from libtmux.session import Session
from libtmux.window import Window

if TYPE_CHECKING:
    from libtmux.server import Server

logger = logging.getLogger(__name__)


# ============================================================================
# Server.acmd() Tests
# ============================================================================


@pytest.mark.asyncio
async def test_server_acmd_basic(server: Server) -> None:
    """Test Server.acmd() basic async command execution.

    Safety: Uses isolated test server from `server` fixture.
    Server socket: libtmux_test{random} - isolated from developer sessions.
    """
    # Test basic command execution
    result = await server.acmd("list-sessions")
    # returncode may be 0 or 1 depending on whether sessions exist
    # The important thing is the command executes asynchronously
    assert result.returncode in {0, 1}
    assert isinstance(result.stdout, list)
    assert isinstance(result.stderr, list)


@pytest.mark.asyncio
async def test_server_acmd_new_session(server: Server) -> None:
    """Test creating session via Server.acmd().

    Safety: Session created in isolated test server only.
    Cleanup: Server fixture finalizer handles session destruction.
    """
    result = await server.acmd("new-session", "-d", "-P", "-F#{session_id}")
    session_id = result.stdout[0]

    # Verify session was created
    assert session_id.startswith("$")
    assert server.has_session(session_id)

    # Verify we can get the session object
    session = Session.from_session_id(session_id=session_id, server=server)
    assert isinstance(session, Session)
    assert session.session_id == session_id


# ============================================================================
# Session.acmd() Tests
# ============================================================================


@pytest.mark.asyncio
async def test_session_acmd_basic(session: Session) -> None:
    """Test Session.acmd() executes in session context.

    Safety: Uses `session` fixture which depends on isolated `server`.
    """
    # List windows in the session
    result = await session.acmd("list-windows", "-F#{window_id}")
    assert len(result.stdout) >= 1
    assert all(wid.startswith("@") for wid in result.stdout)


@pytest.mark.asyncio
async def test_session_acmd_new_window(session: Session) -> None:
    """Test creating window via Session.acmd().

    Safety: Window created in isolated test session only.
    """
    # Get initial window count
    initial_windows = session.windows
    initial_count = len(initial_windows)

    # Create new window asynchronously
    result = await session.acmd("new-window", "-P", "-F#{window_id}")
    window_id = result.stdout[0]
    assert window_id.startswith("@")

    # Refresh session and verify window was created
    # Note: We need to re-query the session to see new window
    result = await session.acmd("list-windows", "-F#{window_id}")
    assert len(result.stdout) == initial_count + 1
    assert window_id in result.stdout


# ============================================================================
# Window.acmd() Tests
# ============================================================================


@pytest.mark.asyncio
async def test_window_acmd_split_pane(session: Session) -> None:
    """Test splitting pane via Window.acmd().

    Safety: Pane created in isolated test window only.
    """
    window = session.active_window
    assert window is not None

    # Get initial pane count
    result = await window.acmd("list-panes", "-F#{pane_id}")
    initial_pane_count = len(result.stdout)

    # Split window to create new pane
    result = await window.acmd("split-window", "-P", "-F#{pane_id}")
    pane_id = result.stdout[0]
    assert pane_id.startswith("%")

    # Verify new pane was created
    result = await window.acmd("list-panes", "-F#{pane_id}")
    assert len(result.stdout) == initial_pane_count + 1
    assert pane_id in result.stdout


# ============================================================================
# Pane.acmd() Tests
# ============================================================================


@pytest.mark.asyncio
async def test_pane_acmd_basic(session: Session) -> None:
    """Test Pane.acmd() executes in pane context.

    Safety: Commands sent to isolated test pane only.
    """
    pane = session.active_pane
    assert pane is not None

    # Display pane ID
    result = await pane.acmd("display-message", "-p", "#{pane_id}")
    assert result.stdout[0] == pane.pane_id


@pytest.mark.asyncio
async def test_pane_acmd_send_keys(session: Session) -> None:
    """Test sending keys via Pane.acmd().

    Safety: Keys sent to isolated test pane only.
    """
    pane = session.active_pane
    assert pane is not None

    # Send echo command
    await pane.acmd("send-keys", "echo 'test_async_pane'", "Enter")

    # Give command time to execute
    await asyncio.sleep(0.2)

    # Capture output
    result = await pane.acmd("capture-pane", "-p")
    assert any("test_async_pane" in line for line in result.stdout)


# ============================================================================
# Concurrent Operations Tests
# ============================================================================


@pytest.mark.asyncio
async def test_concurrent_session_creation(server: Server) -> None:
    """Test creating multiple sessions concurrently.

    Safety: All sessions created in isolated test server.
    Demonstrates async benefit: concurrent tmux operations.
    Cleanup: Server fixture finalizer handles all session destruction.
    """

    async def create_session(index: int) -> Session:
        """Create a session asynchronously."""
        result = await server.acmd(
            "new-session",
            "-d",
            "-P",
            "-F#{session_id}",
            "-s",
            f"concurrent_test_{index}",
        )
        session_id = result.stdout[0]
        return Session.from_session_id(session_id=session_id, server=server)

    # Create 3 sessions concurrently
    sessions = await asyncio.gather(
        create_session(1),
        create_session(2),
        create_session(3),
    )

    # Verify all sessions were created
    assert len(sessions) == 3
    assert all(isinstance(s, Session) for s in sessions)

    # Verify all session IDs are unique
    session_ids = {s.session_id for s in sessions}
    assert len(session_ids) == 3

    # Verify all sessions exist in server
    for session in sessions:
        assert server.has_session(str(session.session_id))


# ============================================================================
# Error Handling Tests
# ============================================================================


@pytest.mark.asyncio
async def test_async_invalid_command(server: Server) -> None:
    """Test async error handling for invalid commands.

    Safety: Invalid commands executed in isolated server only.
    """
    # AsyncTmuxCmd captures errors in stderr rather than raising
    result = await server.acmd("nonexistent-command-xyz")

    # Invalid command should populate stderr
    assert len(result.stderr) > 0
    assert result.returncode != 0


@pytest.mark.asyncio
async def test_async_session_not_found(server: Server) -> None:
    """Test error when targeting nonexistent session.

    Safety: Test only affects isolated server.
    """
    # has-session returns non-zero when session doesn't exist
    result = await server.acmd("has-session", "-t", "nonexistent_session_xyz_123")

    # has-session returns 1 when session doesn't exist
    assert result.returncode != 0


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_async_full_workflow(server: Server) -> None:
    """Test complete async workflow: session -> window -> pane -> command.

    Safety: All objects created in isolated test server.
    Demonstrates comprehensive async tmux manipulation.
    Cleanup: Server fixture finalizer handles all resource destruction.
    """
    # Create session
    result = await server.acmd("new-session", "-d", "-P", "-F#{session_id}")
    session_id = result.stdout[0]
    session = Session.from_session_id(session_id=session_id, server=server)

    # Verify session created
    assert session_id.startswith("$")
    assert server.has_session(session_id)

    # Create window in session
    result = await session.acmd("new-window", "-P", "-F#{window_id}")
    window_id = result.stdout[0]
    window = Window.from_window_id(window_id=window_id, server=server)
    assert window_id.startswith("@")

    # Split pane in window
    result = await window.acmd("split-window", "-P", "-F#{pane_id}")
    pane_id = result.stdout[0]
    pane = Pane.from_pane_id(pane_id=pane_id, server=server)
    assert pane_id.startswith("%")

    # Send command to pane
    await pane.acmd("send-keys", "echo 'integration_test_complete'", "Enter")
    await asyncio.sleep(0.2)

    # Verify output
    result = await pane.acmd("capture-pane", "-p")
    assert any("integration_test_complete" in line for line in result.stdout)

    # Verify complete object hierarchy
    assert session.session_id == session_id
    assert window.window_id == window_id
    assert pane.pane_id == pane_id
