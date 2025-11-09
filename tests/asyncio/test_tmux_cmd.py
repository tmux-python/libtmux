"""Tests for Pattern B: async-first tmux_cmd_async.

These tests verify the psycopg-inspired async-first architecture:
- tmux_cmd_async() function for direct async command execution
- Async version checking functions (get_version, has_gte_version, etc.)
- Integration with isolated test servers
- Complete isolation from developer's sessions
"""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.common_async import (
    get_version,
    has_gte_version,
    has_gt_version,
    has_lt_version,
    has_lte_version,
    has_minimum_version,
    has_version,
    tmux_cmd_async,
)
from libtmux.server import Server

if t.TYPE_CHECKING:
    from collections.abc import Callable


@pytest.mark.asyncio
async def test_tmux_cmd_async_basic(async_server: Server) -> None:
    """Test tmux_cmd_async() with isolated server socket."""
    # Use server's unique socket to ensure isolation
    socket_name = async_server.socket_name
    assert socket_name is not None
    assert socket_name.startswith("libtmux_test")

    # Create session using Pattern B with isolated socket
    result = await tmux_cmd_async(
        "-L",
        socket_name,  # Use isolated socket!
        "new-session",
        "-d",
        "-P",
        "-F#{session_id}",
    )

    # Verify result structure
    assert isinstance(result, tmux_cmd_async)
    assert result.returncode == 0
    assert len(result.stdout) == 1
    assert len(result.stderr) == 0

    # Verify session exists in isolated server
    session_id = result.stdout[0]
    assert async_server.has_session(session_id)

    # No manual cleanup needed - server fixture finalizer handles it


@pytest.mark.asyncio
async def test_async_get_version() -> None:
    """Test async get_version() function."""
    version = await get_version()

    assert version is not None
    assert str(version)  # Has string representation

    # Should match sync version
    from libtmux.common import get_version as sync_get_version

    sync_version = sync_get_version()
    assert version == sync_version


@pytest.mark.asyncio
async def test_async_version_checking_functions() -> None:
    """Test async version checking helper functions."""
    # Get current version
    version = await get_version()
    version_str = str(version)

    # Test has_version
    result = await has_version(version_str)
    assert result is True

    # Test has_minimum_version
    result = await has_minimum_version(raises=False)
    assert result is True

    # Test has_gte_version with current version
    result = await has_gte_version(version_str)
    assert result is True

    # Test has_gt_version with lower version
    result = await has_gt_version("1.0")
    assert result is True

    # Test has_lte_version with current version
    result = await has_lte_version(version_str)
    assert result is True

    # Test has_lt_version with higher version
    result = await has_lt_version("99.0")
    assert result is True


@pytest.mark.asyncio
async def test_concurrent_tmux_cmd_async(async_server: Server) -> None:
    """Test concurrent tmux_cmd_async() operations."""
    socket_name = async_server.socket_name
    assert socket_name is not None

    # Create multiple sessions concurrently
    results = await asyncio.gather(
        *[
            tmux_cmd_async(
                "-L",
                socket_name,
                "new-session",
                "-d",
                "-P",
                "-F#{session_id}",
            )
            for _ in range(5)
        ],
    )

    # All should succeed
    assert all(r.returncode == 0 for r in results)

    # All should have unique IDs
    session_ids = [r.stdout[0] for r in results]
    assert len(set(session_ids)) == 5

    # Verify all exist in isolated server
    for session_id in session_ids:
        assert async_server.has_session(session_id)

    # No manual cleanup needed - server fixture finalizer handles it


@pytest.mark.asyncio
async def test_tmux_cmd_async_error_handling(async_server: Server) -> None:
    """Test tmux_cmd_async() error handling."""
    socket_name = async_server.socket_name
    assert socket_name is not None

    # Create a session first to ensure server socket exists
    result = await tmux_cmd_async(
        "-L",
        socket_name,
        "new-session",
        "-d",
        "-P",
        "-F#{session_id}",
    )
    session_id = result.stdout[0]

    # Invalid command (server socket now exists)
    result = await tmux_cmd_async("-L", socket_name, "invalid-command-99999")

    # Should have error
    assert len(result.stderr) > 0
    assert "unknown command" in result.stderr[0].lower()

    # Non-existent session
    result = await tmux_cmd_async(
        "-L",
        socket_name,
        "has-session",
        "-t",
        "nonexistent_99999",
    )

    # Command fails
    assert result.returncode != 0
    assert len(result.stderr) > 0

    # No manual cleanup needed - server fixture finalizer handles it


@pytest.mark.asyncio
async def test_tmux_cmd_async_with_multiple_servers(
    async_test_server: Callable[..., Server],
) -> None:
    """Test tmux_cmd_async() with multiple isolated servers."""
    # Create two servers with unique sockets
    server1 = async_test_server()
    server2 = async_test_server()

    socket1 = server1.socket_name
    socket2 = server2.socket_name

    assert socket1 is not None
    assert socket2 is not None
    assert socket1 != socket2

    # Create sessions on both servers with same name
    result1 = await tmux_cmd_async(
        "-L",
        socket1,
        "new-session",
        "-d",
        "-s",
        "test",
        "-P",
        "-F#{session_id}",
    )
    result2 = await tmux_cmd_async(
        "-L",
        socket2,
        "new-session",
        "-d",
        "-s",
        "test",
        "-P",
        "-F#{session_id}",
    )

    # Both succeed (different sockets = different namespaces)
    assert result1.returncode == 0
    assert result2.returncode == 0

    # Session IDs may be same ($0 on each socket) but sockets are different
    # The key test is isolation, not ID uniqueness
    assert socket1 != socket2  # Different sockets = true isolation

    # Verify isolation - each server sees only its own session
    assert server1.has_session("test")
    assert server2.has_session("test")
    assert len(server1.sessions) == 1
    assert len(server2.sessions) == 1


@pytest.mark.asyncio
async def test_tmux_cmd_async_list_operations(async_server: Server) -> None:
    """Test tmux_cmd_async() with list operations."""
    socket_name = async_server.socket_name
    assert socket_name is not None

    # Create a session
    result = await tmux_cmd_async(
        "-L",
        socket_name,
        "new-session",
        "-d",
        "-s",
        "test_list",
        "-P",
        "-F#{session_id}",
    )
    assert result.returncode == 0

    # List sessions
    result = await tmux_cmd_async("-L", socket_name, "list-sessions")
    assert result.returncode == 0
    assert len(result.stdout) >= 1
    assert any("test_list" in line for line in result.stdout)

    # List windows
    result = await tmux_cmd_async(
        "-L",
        socket_name,
        "list-windows",
        "-t",
        "test_list",
    )
    assert result.returncode == 0
    assert len(result.stdout) >= 1

    # List panes
    result = await tmux_cmd_async(
        "-L",
        socket_name,
        "list-panes",
        "-t",
        "test_list",
    )
    assert result.returncode == 0
    assert len(result.stdout) >= 1


@pytest.mark.asyncio
async def test_tmux_cmd_async_window_operations(async_server: Server) -> None:
    """Test tmux_cmd_async() window creation and manipulation."""
    socket_name = async_server.socket_name
    assert socket_name is not None

    # Create session
    result = await tmux_cmd_async(
        "-L",
        socket_name,
        "new-session",
        "-d",
        "-s",
        "test_windows",
        "-P",
        "-F#{session_id}",
    )
    session_id = result.stdout[0]

    # Create new window
    result = await tmux_cmd_async(
        "-L",
        socket_name,
        "new-window",
        "-t",
        session_id,
        "-n",
        "my_window",
        "-P",
        "-F#{window_index}",
    )
    assert result.returncode == 0
    window_index = result.stdout[0]

    # Verify window exists
    result = await tmux_cmd_async(
        "-L",
        socket_name,
        "list-windows",
        "-t",
        session_id,
        "-F#{window_index}:#{window_name}",
    )
    assert any(f"{window_index}:my_window" in line for line in result.stdout)


@pytest.mark.asyncio
async def test_tmux_cmd_async_pane_operations(async_server: Server) -> None:
    """Test tmux_cmd_async() pane splitting and manipulation."""
    socket_name = async_server.socket_name
    assert socket_name is not None

    # Create session
    result = await tmux_cmd_async(
        "-L",
        socket_name,
        "new-session",
        "-d",
        "-s",
        "test_panes",
        "-P",
        "-F#{session_id}",
    )
    session_id = result.stdout[0]

    # Split pane
    result = await tmux_cmd_async(
        "-L",
        socket_name,
        "split-window",
        "-t",
        session_id,
        "-P",
        "-F#{pane_id}",
    )
    assert result.returncode == 0
    new_pane_id = result.stdout[0]

    # Verify pane was created
    result = await tmux_cmd_async(
        "-L",
        socket_name,
        "list-panes",
        "-t",
        session_id,
        "-F#{pane_id}",
    )
    assert new_pane_id in result.stdout
    assert len(result.stdout) >= 2  # At least 2 panes now


@pytest.mark.asyncio
async def test_has_minimum_version_raises_on_old_version() -> None:
    """Test has_minimum_version raises exception for old tmux version."""
    from libtmux import exc
    from libtmux._compat import LooseVersion
    from unittest.mock import AsyncMock, patch

    # Mock get_version to return old version (below minimum)
    mock_old_version = AsyncMock(return_value=LooseVersion("1.0"))

    with patch("libtmux.common_async.get_version", mock_old_version):
        # Should raise VersionTooLow exception
        with pytest.raises(exc.VersionTooLow, match="libtmux only supports tmux"):
            await has_minimum_version(raises=True)


@pytest.mark.asyncio
async def test_has_minimum_version_returns_false_without_raising() -> None:
    """Test has_minimum_version returns False without raising when raises=False."""
    from libtmux._compat import LooseVersion
    from unittest.mock import AsyncMock, patch

    # Mock get_version to return old version (below minimum)
    mock_old_version = AsyncMock(return_value=LooseVersion("1.0"))

    with patch("libtmux.common_async.get_version", mock_old_version):
        # Should return False without raising
        result = await has_minimum_version(raises=False)
        assert result is False


@pytest.mark.asyncio
async def test_version_comparison_boundary_conditions() -> None:
    """Test version comparison functions at exact boundaries."""
    # Get actual current version
    current_version = await get_version()
    current_version_str = str(current_version)

    # Test exact match scenarios
    assert await has_version(current_version_str) is True
    assert await has_gte_version(current_version_str) is True
    assert await has_lte_version(current_version_str) is True

    # Test false scenarios
    assert await has_version("999.999") is False
    assert await has_gt_version("999.999") is False
    assert await has_lt_version("0.1") is False


@pytest.mark.asyncio
async def test_version_comparison_with_minimum_version() -> None:
    """Test version comparisons against TMUX_MIN_VERSION."""
    from libtmux.common_async import TMUX_MIN_VERSION

    # Current version should be >= minimum
    assert await has_gte_version(TMUX_MIN_VERSION) is True

    # Should not be less than minimum
    assert await has_lt_version(TMUX_MIN_VERSION) is False

    # has_minimum_version should pass
    assert await has_minimum_version(raises=False) is True
