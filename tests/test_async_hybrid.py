"""Tests for hybrid usage: both Pattern A and Pattern B together.

These tests verify that both async patterns can be used together:
- Pattern A: .acmd() methods on Server/Session/Window/Pane
- Pattern B: tmux_cmd_async() direct async command execution

Both patterns work on the same isolated test servers and can be
mixed freely without interference.
"""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.common import AsyncTmuxCmd
from libtmux.common_async import tmux_cmd_async
from libtmux.server import Server

if t.TYPE_CHECKING:
    from collections.abc import Callable


@pytest.mark.asyncio
async def test_both_patterns_same_server(async_server: Server) -> None:
    """Test both patterns work on same isolated server."""
    socket_name = async_server.socket_name
    assert socket_name is not None

    # Pattern A: .acmd() on server instance
    result_a = await async_server.acmd("new-session", "-d", "-P", "-F#{session_id}")
    session_a = result_a.stdout[0]

    # Pattern B: tmux_cmd_async with same socket
    result_b = await tmux_cmd_async(
        "-L",
        socket_name,
        "new-session",
        "-d",
        "-P",
        "-F#{session_id}",
    )
    session_b = result_b.stdout[0]

    # Both sessions should exist on same isolated server
    assert async_server.has_session(session_a)
    assert async_server.has_session(session_b)
    assert session_a != session_b

    # Server should see both
    assert len(async_server.sessions) == 2

    # Cleanup both concurrently (mixing patterns!)
    await asyncio.gather(
        async_server.acmd("kill-session", "-t", session_a),
        tmux_cmd_async("-L", socket_name, "kill-session", "-t", session_b),
    )


@pytest.mark.asyncio
async def test_pattern_results_compatible(async_server: Server) -> None:
    """Test both pattern results have compatible structure."""
    socket_name = async_server.socket_name
    assert socket_name is not None

    # Get list of sessions from both patterns
    result_a = await async_server.acmd("list-sessions")
    result_b = await tmux_cmd_async("-L", socket_name, "list-sessions")

    # Both should have same attributes
    assert hasattr(result_a, "stdout")
    assert hasattr(result_b, "stdout")
    assert hasattr(result_a, "stderr")
    assert hasattr(result_b, "stderr")
    assert hasattr(result_a, "returncode")
    assert hasattr(result_b, "returncode")

    # Results should be similar
    assert result_a.returncode == result_b.returncode
    assert isinstance(result_a.stdout, list)
    assert isinstance(result_b.stdout, list)
    assert isinstance(result_a.stderr, list)
    assert isinstance(result_b.stderr, list)

    # Type assertions
    assert isinstance(result_a, AsyncTmuxCmd)
    assert isinstance(result_b, tmux_cmd_async)


@pytest.mark.asyncio
async def test_concurrent_mixed_patterns(async_test_server: Callable[..., Server]) -> None:
    """Test concurrent operations mixing both patterns."""
    server = async_test_server()
    socket_name = server.socket_name
    assert socket_name is not None

    # Run mixed pattern operations concurrently
    results = await asyncio.gather(
        # Pattern A operations
        server.acmd("new-session", "-d", "-P", "-F#{session_id}"),
        server.acmd("new-session", "-d", "-P", "-F#{session_id}"),
        # Pattern B operations
        tmux_cmd_async(
            "-L",
            socket_name,
            "new-session",
            "-d",
            "-P",
            "-F#{session_id}",
        ),
        tmux_cmd_async(
            "-L",
            socket_name,
            "new-session",
            "-d",
            "-P",
            "-F#{session_id}",
        ),
    )

    # All should succeed
    assert all(r.returncode == 0 for r in results)

    # Extract session IDs
    session_ids = [r.stdout[0] for r in results]
    assert len(set(session_ids)) == 4

    # Verify all exist
    for session_id in session_ids:
        assert server.has_session(session_id)

    # Cleanup with mixed patterns
    await asyncio.gather(
        server.acmd("kill-session", "-t", session_ids[0]),
        server.acmd("kill-session", "-t", session_ids[1]),
        tmux_cmd_async("-L", socket_name, "kill-session", "-t", session_ids[2]),
        tmux_cmd_async("-L", socket_name, "kill-session", "-t", session_ids[3]),
    )


@pytest.mark.asyncio
async def test_both_patterns_different_servers(
    async_test_server: Callable[..., Server],
) -> None:
    """Test each pattern on different isolated server."""
    server1 = async_test_server()
    server2 = async_test_server()

    socket1 = server1.socket_name
    socket2 = server2.socket_name

    assert socket1 is not None
    assert socket2 is not None
    assert socket1 != socket2

    # Pattern A on server1
    result_a = await server1.acmd("new-session", "-d", "-s", "pattern_a", "-P", "-F#{session_id}")

    # Pattern B on server2
    result_b = await tmux_cmd_async(
        "-L",
        socket2,
        "new-session",
        "-d",
        "-s",
        "pattern_b",
        "-P",
        "-F#{session_id}",
    )

    # Both succeed
    assert result_a.returncode == 0
    assert result_b.returncode == 0

    # Verify isolation
    assert server1.has_session("pattern_a")
    assert not server1.has_session("pattern_b")
    assert not server2.has_session("pattern_a")
    assert server2.has_session("pattern_b")


@pytest.mark.asyncio
async def test_hybrid_window_operations(async_server: Server) -> None:
    """Test window operations with both patterns."""
    socket_name = async_server.socket_name
    assert socket_name is not None

    # Create session with Pattern A
    result = await async_server.acmd("new-session", "-d", "-s", "hybrid_test", "-P", "-F#{session_id}")
    session_id = result.stdout[0]

    # Create window with Pattern B
    result_b = await tmux_cmd_async(
        "-L",
        socket_name,
        "new-window",
        "-t",
        session_id,
        "-n",
        "window_b",
        "-P",
        "-F#{window_index}",
    )
    assert result_b.returncode == 0

    # Create window with Pattern A
    result_a = await async_server.acmd(
        "new-window",
        "-t",
        session_id,
        "-n",
        "window_a",
        "-P",
        "-F#{window_index}",
    )
    assert result_a.returncode == 0

    # List windows with both patterns
    list_a = await async_server.acmd("list-windows", "-t", session_id, "-F#{window_name}")
    list_b = await tmux_cmd_async(
        "-L",
        socket_name,
        "list-windows",
        "-t",
        session_id,
        "-F#{window_name}",
    )

    # Both should see same windows
    assert "window_a" in list_a.stdout
    assert "window_b" in list_a.stdout
    assert "window_a" in list_b.stdout
    assert "window_b" in list_b.stdout


@pytest.mark.asyncio
async def test_hybrid_pane_operations(async_server: Server) -> None:
    """Test pane operations with both patterns."""
    socket_name = async_server.socket_name
    assert socket_name is not None

    # Create session
    result = await async_server.acmd("new-session", "-d", "-s", "pane_test", "-P", "-F#{session_id}")
    session_id = result.stdout[0]

    # Split pane with Pattern A
    result_a = await async_server.acmd(
        "split-window",
        "-t",
        session_id,
        "-P",
        "-F#{pane_id}",
    )
    pane_a = result_a.stdout[0]

    # Split pane with Pattern B
    result_b = await tmux_cmd_async(
        "-L",
        socket_name,
        "split-window",
        "-t",
        session_id,
        "-P",
        "-F#{pane_id}",
    )
    pane_b = result_b.stdout[0]

    # Should have 3 panes total (1 initial + 2 splits)
    list_panes = await async_server.acmd("list-panes", "-t", session_id)
    assert len(list_panes.stdout) == 3

    # Both created panes should exist
    pane_ids_a = await async_server.acmd("list-panes", "-t", session_id, "-F#{pane_id}")
    pane_ids_b = await tmux_cmd_async(
        "-L",
        socket_name,
        "list-panes",
        "-t",
        session_id,
        "-F#{pane_id}",
    )

    assert pane_a in pane_ids_a.stdout
    assert pane_b in pane_ids_a.stdout
    assert pane_a in pane_ids_b.stdout
    assert pane_b in pane_ids_b.stdout


@pytest.mark.asyncio
async def test_hybrid_error_handling(async_server: Server) -> None:
    """Test error handling works the same in both patterns."""
    socket_name = async_server.socket_name
    assert socket_name is not None

    # Both patterns handle errors similarly

    # Pattern A: invalid command
    result_a = await async_server.acmd("invalid-command-xyz")
    assert len(result_a.stderr) > 0

    # Pattern B: invalid command
    result_b = await tmux_cmd_async("-L", socket_name, "invalid-command-xyz")
    assert len(result_b.stderr) > 0

    # Both should have similar error messages
    assert "unknown command" in result_a.stderr[0].lower()
    assert "unknown command" in result_b.stderr[0].lower()
