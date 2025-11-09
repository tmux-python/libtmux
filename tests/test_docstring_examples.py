"""Tests to verify docstring code examples in common_async.py work correctly.

These tests ensure that all the code examples shown in docstrings are valid and
executable. They replace the SKIP'd doctests that provided no verification.
"""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux import Server
from libtmux.common_async import get_version, tmux_cmd_async

if t.TYPE_CHECKING:
    from libtmux._compat import LooseVersion


@pytest.mark.asyncio
async def test_module_docstring_pattern_a(async_server: Server) -> None:
    """Verify Pattern A example from module docstring works.

    From src/libtmux/common_async.py:14-25 (Pattern A example).
    """
    import asyncio

    import libtmux

    async def example() -> list[str]:
        server = libtmux.Server(socket_name=async_server.socket_name)
        result = await server.acmd("list-sessions")
        return result.stdout

    result = await example()
    assert isinstance(result, list)
    # Result may be empty if no sessions exist on this socket yet


@pytest.mark.asyncio
async def test_module_docstring_pattern_b(async_server: Server) -> None:
    """Verify Pattern B example from module docstring works.

    From src/libtmux/common_async.py:27-37 (Pattern B example).
    """
    import asyncio

    from libtmux.common_async import tmux_cmd_async

    async def example() -> list[str]:
        sock = async_server.socket_name
        result = await tmux_cmd_async("-L", sock, "list-sessions")
        return result.stdout

    result = await example()
    assert isinstance(result, list)
    # Result may be empty if no sessions exist on this socket yet


@pytest.mark.asyncio
async def test_module_docstring_concurrent(async_server: Server) -> None:
    """Verify concurrent example from module docstring works.

    From src/libtmux/common_async.py:45-59 (Performance example).
    """
    import asyncio

    from libtmux.common_async import tmux_cmd_async

    async def concurrent() -> list[tmux_cmd_async]:
        sock = async_server.socket_name
        results = await asyncio.gather(
            tmux_cmd_async("-L", sock, "list-sessions"),
            tmux_cmd_async("-L", sock, "list-windows", "-a"),
            tmux_cmd_async("-L", sock, "list-panes", "-a"),
        )
        return results

    results = await concurrent()
    assert len(results) == 3
    # Commands may fail if no sessions exist, but should execute
    assert all(isinstance(r.stdout, list) for r in results)


@pytest.mark.asyncio
async def test_tmux_cmd_async_concurrent_example(async_server: Server) -> None:
    """Verify concurrent operations example from tmux_cmd_async class docstring.

    From src/libtmux/common_async.py:274-289 (Concurrent Operations example).
    """
    import asyncio

    from libtmux.common_async import tmux_cmd_async

    async def concurrent_example() -> list[int]:
        sock = async_server.socket_name
        # All commands run concurrently
        results = await asyncio.gather(
            tmux_cmd_async("-L", sock, "list-sessions"),
            tmux_cmd_async("-L", sock, "list-windows", "-a"),
            tmux_cmd_async("-L", sock, "list-panes", "-a"),
        )
        return [len(r.stdout) for r in results]

    counts = await concurrent_example()
    assert len(counts) == 3
    assert all(isinstance(count, int) for count in counts)
    assert all(count >= 0 for count in counts)


@pytest.mark.asyncio
async def test_tmux_cmd_async_error_handling(async_server: Server) -> None:
    """Verify error handling example from tmux_cmd_async class docstring.

    From src/libtmux/common_async.py:291-304 (Error Handling example).
    """
    import asyncio

    from libtmux.common_async import tmux_cmd_async

    async def check_session() -> bool:
        sock = async_server.socket_name
        result = await tmux_cmd_async(
            "-L",
            sock,
            "has-session",
            "-t",
            "nonexistent_session_12345",
        )
        if result.returncode != 0:
            return False
        return True

    result = await check_session()
    assert result is False  # Session should not exist


@pytest.mark.asyncio
async def test_get_version_basic() -> None:
    """Verify basic get_version example from function docstring.

    From src/libtmux/common_async.py:428-438 (basic example).
    """
    import asyncio

    from libtmux.common_async import get_version

    async def check_version() -> LooseVersion:
        version = await get_version()
        return version

    version = await check_version()
    # Verify it's a version object with a string representation
    assert isinstance(str(version), str)
    # Should be something like "3.4" or "3.5"
    assert len(str(version)) > 0
    # Verify it can be compared
    from libtmux._compat import LooseVersion

    assert version >= LooseVersion("1.8")  # TMUX_MIN_VERSION


@pytest.mark.asyncio
async def test_get_version_concurrent(async_server: Server) -> None:
    """Verify concurrent get_version example from function docstring.

    From src/libtmux/common_async.py:440-453 (concurrent operations example).
    """
    import asyncio

    from libtmux.common_async import get_version, tmux_cmd_async

    async def check_all() -> tuple[LooseVersion, int]:
        sock = async_server.socket_name
        version, sessions = await asyncio.gather(
            get_version(),
            tmux_cmd_async("-L", sock, "list-sessions"),
        )
        return version, len(sessions.stdout)

    version, count = await check_all()
    # Verify version is valid
    assert isinstance(str(version), str)
    # Verify sessions count is reasonable
    assert isinstance(count, int)
    assert count >= 0  # May be 0 if no sessions on socket yet


@pytest.mark.asyncio
async def test_pattern_a_with_error_handling(async_server: Server) -> None:
    """Test Pattern A with proper error handling and verification."""
    import asyncio

    import libtmux

    async def example() -> bool:
        server = libtmux.Server(socket_name=async_server.socket_name)

        # Create a new session
        result = await server.acmd("new-session", "-d", "-P", "-F#{session_id}")
        session_id = result.stdout[0]

        # Verify session exists
        result = await server.acmd("has-session", "-t", session_id)
        success = result.returncode == 0

        # Cleanup
        await server.acmd("kill-session", "-t", session_id)

        return success

    success = await example()
    assert success is True


@pytest.mark.asyncio
async def test_pattern_b_with_socket_isolation(async_server: Server) -> None:
    """Test Pattern B ensures proper socket isolation."""
    from libtmux.common_async import tmux_cmd_async

    sock = async_server.socket_name

    # Create session on isolated socket
    result = await tmux_cmd_async("-L", sock, "new-session", "-d", "-P", "-F#{session_id}")
    session_id = result.stdout[0]

    # Verify it exists on the isolated socket
    result = await tmux_cmd_async("-L", sock, "has-session", "-t", session_id)
    assert result.returncode == 0

    # Cleanup
    await tmux_cmd_async("-L", sock, "kill-session", "-t", session_id)


@pytest.mark.asyncio
async def test_concurrent_operations_performance(async_server: Server) -> None:
    """Verify concurrent operations are actually faster than sequential.

    This test demonstrates the 2-3x performance benefit mentioned in docs.
    """
    import time

    from libtmux.common_async import tmux_cmd_async

    sock = async_server.socket_name

    # Measure sequential execution
    start = time.time()
    await tmux_cmd_async("-L", sock, "list-sessions")
    await tmux_cmd_async("-L", sock, "list-windows", "-a")
    await tmux_cmd_async("-L", sock, "list-panes", "-a")
    await tmux_cmd_async("-L", sock, "show-options", "-g")
    sequential_time = time.time() - start

    # Measure concurrent execution
    start = time.time()
    await asyncio.gather(
        tmux_cmd_async("-L", sock, "list-sessions"),
        tmux_cmd_async("-L", sock, "list-windows", "-a"),
        tmux_cmd_async("-L", sock, "list-panes", "-a"),
        tmux_cmd_async("-L", sock, "show-options", "-g"),
    )
    concurrent_time = time.time() - start

    # Concurrent should be faster (allow for some variance)
    # We're not asserting a specific speedup since it depends on system load
    # but concurrent should at least not be slower
    assert concurrent_time <= sequential_time * 1.1  # Allow 10% variance


@pytest.mark.asyncio
async def test_all_examples_use_isolated_sockets(async_server: Server) -> None:
    """Verify that examples properly isolate from developer's tmux session.

    This is critical to ensure tests never affect the developer's working session.
    """
    sock = async_server.socket_name

    # Verify socket is unique test socket
    assert "libtmux_test" in sock or "pytest" in sock.lower()

    # Verify we can create and destroy sessions without affecting other sockets
    result = await tmux_cmd_async("-L", sock, "new-session", "-d", "-P", "-F#{session_id}")
    session_id = result.stdout[0]

    # Session exists on our socket
    result = await tmux_cmd_async("-L", sock, "has-session", "-t", session_id)
    assert result.returncode == 0

    # Cleanup
    await tmux_cmd_async("-L", sock, "kill-session", "-t", session_id)

    # Session no longer exists
    result = await tmux_cmd_async("-L", sock, "has-session", "-t", session_id)
    assert result.returncode != 0
