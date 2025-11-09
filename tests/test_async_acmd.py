"""Tests for Pattern A: .acmd() methods on existing classes.

These tests verify that the .acmd() async methods work correctly with
libtmux's proven test isolation mechanisms:
- Each test uses unique socket name (libtmux_test{random})
- Never interferes with developer's working tmux sessions
- Automatic cleanup via pytest finalizers
"""

from __future__ import annotations

import asyncio
import time
import typing as t

import pytest

from libtmux.common import AsyncTmuxCmd
from libtmux.server import Server
from libtmux.session import Session

if t.TYPE_CHECKING:
    from collections.abc import Callable


@pytest.mark.asyncio
async def test_server_acmd_basic(async_server: Server) -> None:
    """Test basic Server.acmd() usage with isolated server."""
    # Verify we have unique socket for isolation
    assert async_server.socket_name is not None
    assert async_server.socket_name.startswith("libtmux_test")

    # Create session asynchronously
    result = await async_server.acmd("new-session", "-d", "-P", "-F#{session_id}")

    # Verify result structure
    assert isinstance(result, AsyncTmuxCmd)
    assert result.returncode == 0
    assert len(result.stdout) == 1
    assert len(result.stderr) == 0

    # Verify session was created in isolated server
    session_id = result.stdout[0]
    assert async_server.has_session(session_id)

    # No manual cleanup needed - server fixture finalizer kills entire server


@pytest.mark.asyncio
async def test_server_acmd_with_unique_socket(async_server: Server) -> None:
    """Verify socket isolation prevents interference."""
    socket_name = async_server.socket_name
    assert socket_name is not None

    # Socket name should be unique test socket
    assert socket_name.startswith("libtmux_test")
    assert len(socket_name) > len("libtmux_test")  # Has random suffix

    # Create session
    result = await async_server.acmd(
        "new-session",
        "-d",
        "-s",
        "isolated_test",
        "-P",
        "-F#{session_id}",
    )

    assert result.returncode == 0
    assert async_server.has_session("isolated_test")

    # This session is completely isolated from default tmux socket
    # Developer's tmux sessions are on different socket and unaffected


@pytest.mark.asyncio
async def test_session_acmd_operations(async_server: Server) -> None:
    """Test Session.acmd() async operations."""
    # Create session
    result = await async_server.acmd("new-session", "-d", "-P", "-F#{session_id}")
    session_id = result.stdout[0]

    # Get session object
    session = Session.from_session_id(session_id=session_id, server=async_server)

    # Use session.acmd() to list windows
    result = await session.acmd("list-windows", "-F#{window_index}:#{window_name}")

    assert result.returncode == 0
    assert len(result.stdout) >= 1  # At least one window

    # Create new window via session.acmd()
    result = await session.acmd(
        "new-window",
        "-P",
        "-F#{window_index}",
        "-n",
        "test_window",
    )

    assert result.returncode == 0
    window_index = result.stdout[0]

    # Verify window exists
    result = await session.acmd("list-windows", "-F#{window_index}")
    assert window_index in result.stdout


@pytest.mark.asyncio
async def test_concurrent_acmd_operations(async_server: Server) -> None:
    """Test concurrent .acmd() calls demonstrate async performance."""
    # Create 5 sessions concurrently
    start = time.time()
    results = await asyncio.gather(
        async_server.acmd("new-session", "-d", "-P", "-F#{session_id}"),
        async_server.acmd("new-session", "-d", "-P", "-F#{session_id}"),
        async_server.acmd("new-session", "-d", "-P", "-F#{session_id}"),
        async_server.acmd("new-session", "-d", "-P", "-F#{session_id}"),
        async_server.acmd("new-session", "-d", "-P", "-F#{session_id}"),
    )
    elapsed = time.time() - start

    # All should succeed
    assert all(r.returncode == 0 for r in results)
    assert all(isinstance(r, AsyncTmuxCmd) for r in results)

    # Extract and verify unique session IDs
    session_ids = [r.stdout[0] for r in results]
    assert len(set(session_ids)) == 5, "All session IDs should be unique"

    # Verify all sessions exist in isolated server
    for session_id in session_ids:
        assert async_server.has_session(session_id)

    # Performance logging (should be faster than sequential)
    print(f"\nConcurrent operations completed in {elapsed:.4f}s")

    # No manual cleanup needed - server fixture finalizer handles it


@pytest.mark.asyncio
async def test_acmd_error_handling(async_server: Server) -> None:
    """Test .acmd() properly handles errors."""
    # Create a session first to ensure server socket exists
    result = await async_server.acmd("new-session", "-d", "-P", "-F#{session_id}")
    session_id = result.stdout[0]

    # Invalid command (server socket now exists)
    result = await async_server.acmd("invalid-command-12345")

    # Should have error in stderr
    assert len(result.stderr) > 0
    assert "unknown command" in result.stderr[0].lower()

    # Non-existent session
    result = await async_server.acmd("has-session", "-t", "nonexistent_session_99999")

    # Command fails but returns result
    assert result.returncode != 0
    assert len(result.stderr) > 0

    # No manual cleanup needed - server fixture finalizer handles it


@pytest.mark.asyncio
async def test_multiple_servers_acmd(async_test_server: Callable[..., Server]) -> None:
    """Test multiple servers don't interfere - uses TestServer factory."""
    # Create two independent servers with unique sockets
    server1 = async_test_server()
    server2 = async_test_server()

    # Verify different sockets (isolation guarantee)
    assert server1.socket_name != server2.socket_name
    assert server1.socket_name is not None
    assert server2.socket_name is not None

    # Create sessions with SAME NAME on different servers
    result1 = await server1.acmd(
        "new-session",
        "-d",
        "-s",
        "test",
        "-P",
        "-F#{session_id}",
    )
    result2 = await server2.acmd(
        "new-session",
        "-d",
        "-s",
        "test",
        "-P",
        "-F#{session_id}",
    )

    # Both succeed despite same session name (different sockets!)
    assert result1.returncode == 0
    assert result2.returncode == 0

    # Verify isolation - each server sees only its own session
    assert server1.has_session("test")
    assert server2.has_session("test")
    assert len(server1.sessions) == 1
    assert len(server2.sessions) == 1

    # Sessions are different despite same name and ID (different sockets!)
    session1 = server1.sessions[0]
    session2 = server2.sessions[0]
    # Session IDs may be same ($0) but they're on different sockets
    assert session1.server.socket_name != session2.server.socket_name
    # Verify actual isolation - sessions are truly separate
    assert session1.session_name == session2.session_name == "test"

    # No manual cleanup needed - TestServer finalizer kills all servers


@pytest.mark.asyncio
async def test_window_acmd_operations(async_server: Server) -> None:
    """Test Window.acmd() async operations."""
    # Create session and get window
    result = await async_server.acmd("new-session", "-d", "-P", "-F#{session_id}")
    session_id = result.stdout[0]
    session = Session.from_session_id(session_id=session_id, server=async_server)

    window = session.active_window
    assert window is not None

    # Use window.acmd() to split pane
    result = await window.acmd("split-window", "-P", "-F#{pane_id}")

    assert result.returncode == 0
    pane_id = result.stdout[0]

    # Verify pane was created
    result = await window.acmd("list-panes", "-F#{pane_id}")
    assert pane_id in result.stdout


@pytest.mark.asyncio
async def test_pane_acmd_operations(async_server: Server) -> None:
    """Test Pane.acmd() async operations."""
    # Create session
    result = await async_server.acmd("new-session", "-d", "-P", "-F#{session_id}")
    session_id = result.stdout[0]
    session = Session.from_session_id(session_id=session_id, server=async_server)

    pane = session.active_pane
    assert pane is not None

    # Use pane.acmd() to send keys
    result = await pane.acmd("send-keys", "echo test", "Enter")

    assert result.returncode == 0

    # Give tmux a moment to process
    await asyncio.sleep(0.1)

    # Capture pane content
    result = await pane.acmd("capture-pane", "-p")

    # Should have some output
    assert result.returncode == 0
    assert len(result.stdout) > 0
