"""Tests for Server async operations.

SAFETY: All tests use isolated test servers via fixtures.
Socket names: libtmux_test{8_random_chars} - never affects developer sessions.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from libtmux.session import Session


@dataclass(slots=True)
class SessionQueryInfo:
    """Structured data returned from async session queries."""

    id: str
    name: str
    windows: int


if TYPE_CHECKING:
    from libtmux.server import Server

logger = logging.getLogger(__name__)


# ============================================================================
# Server.acmd() Basic Tests
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
    session_obj_id = session.session_id
    assert session_obj_id is not None
    assert session_obj_id == session_id


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
    session_ids: set[str] = set()
    for session in sessions:
        assert session.session_id is not None
        session_ids.add(session.session_id)
    assert len(session_ids) == 3

    # Verify all sessions exist in server
    for session_id in session_ids:
        assert server.has_session(session_id)


@pytest.mark.asyncio
async def test_concurrent_session_queries(server: Server) -> None:
    """Test querying multiple sessions concurrently.

    Safety: All sessions created/queried in isolated test server.
    Demonstrates async benefit: parallel queries faster than sequential.
    """
    # Create 5 sessions first
    session_ids = []
    for i in range(5):
        result = await server.acmd(
            "new-session",
            "-d",
            "-P",
            "-F#{session_id}",
            "-s",
            f"query_test_{i}",
        )
        session_ids.append(result.stdout[0])

    async def query_session(session_id: str) -> SessionQueryInfo:
        """Query session information asynchronously."""
        result = await server.acmd(
            "display-message",
            "-t",
            session_id,
            "-p",
            "#{session_id}:#{session_name}:#{session_windows}",
        )
        output = result.stdout[0]
        parts = output.split(":")
        return SessionQueryInfo(id=parts[0], name=parts[1], windows=int(parts[2]))

    # Query all sessions concurrently
    results: list[SessionQueryInfo] = await asyncio.gather(
        *[query_session(sid) for sid in session_ids]
    )

    # Verify all queries returned valid data
    assert len(results) == 5
    for i, info in enumerate(results):
        assert info.id == session_ids[i]
        assert info.name == f"query_test_{i}"
        assert info.windows >= 1


@pytest.mark.asyncio
async def test_batch_session_operations(server: Server) -> None:
    """Test batch create and verify pattern.

    Safety: All operations in isolated test server.
    Real-world pattern: Set up multiple sessions efficiently.
    """
    session_names = [
        "dev_frontend",
        "dev_backend",
        "dev_database",
        "logs_monitoring",
    ]

    async def create_and_verify(name: str) -> tuple[str, bool]:
        """Create session and verify it exists."""
        result = await server.acmd(
            "new-session",
            "-d",
            "-P",
            "-F#{session_id}",
            "-s",
            name,
        )
        session_id = result.stdout[0]

        # Verify via has-session
        check_result = await server.acmd("has-session", "-t", name)
        exists = check_result.returncode == 0

        return (session_id, exists)

    # Create all sessions concurrently
    results = await asyncio.gather(*[create_and_verify(name) for name in session_names])

    # Verify all sessions were created and verified
    assert len(results) == 4
    for (session_id, exists), name in zip(results, session_names, strict=False):
        assert session_id.startswith("$")
        assert exists, f"Session {name} not found after creation"
        assert server.has_session(name)


# ============================================================================
# Server.anew_session() Tests
# ============================================================================


@pytest.mark.asyncio
async def test_anew_session_basic(server: Server) -> None:
    """Test Server.anew_session() creates session.

    Safety: Session created in isolated test server.
    Demonstrates: High-level async session creation API.
    """
    session = await server.anew_session("test_anew_session")

    # Verify session created with correct properties
    session_name = session.session_name
    assert session_name is not None
    assert session_name == "test_anew_session"
    assert server.has_session("test_anew_session")
    assert isinstance(session, Session)
    session_id = session.session_id
    assert session_id is not None
    assert session_id.startswith("$")


@pytest.mark.asyncio
async def test_anew_session_with_environment(server: Server) -> None:
    """Test Server.anew_session() with environment variables.

    Safety: Session with env vars created in isolated test server.
    Real-world pattern: Pass environment configuration to session.
    """
    env_vars = {
        "TEST_VAR": "test_value",
        "ANOTHER_VAR": "another_value",
    }

    session = await server.anew_session(
        "test_env_session",
        environment=env_vars,
    )

    # Verify session created
    env_session_name = session.session_name
    assert env_session_name is not None
    assert env_session_name == "test_env_session"
    assert server.has_session("test_env_session")

    # Verify environment variables were set
    # Query environment in the session's pane
    result = await session.acmd(
        "show-environment",
        "-s",
        "TEST_VAR",
    )
    # tmux formats env vars as: TEST_VAR="test_value"; export TEST_VAR;
    assert "TEST_VAR" in result.stdout[0]
    assert "test_value" in result.stdout[0]


@pytest.mark.asyncio
async def test_anew_session_concurrent(server: Server) -> None:
    """Test creating multiple sessions concurrently via anew_session().

    Safety: All sessions created in isolated test server.
    Demonstrates: Async benefit - concurrent high-level session creation.
    """

    async def create_session(name: str) -> Session:
        """Create session using anew_session()."""
        return await server.anew_session(name)

    # Create 4 sessions concurrently
    sessions = await asyncio.gather(
        create_session("concurrent_a"),
        create_session("concurrent_b"),
        create_session("concurrent_c"),
        create_session("concurrent_d"),
    )

    # Verify all sessions created
    assert len(sessions) == 4
    assert all(isinstance(s, Session) for s in sessions)

    # Verify all have unique IDs and correct names
    expected_names = ["concurrent_a", "concurrent_b", "concurrent_c", "concurrent_d"]
    actual_names: list[str] = []
    for session in sessions:
        assert session.session_name is not None
        actual_names.append(session.session_name)
    assert sorted(actual_names) == sorted(expected_names)

    # Verify all exist in server
    for name in actual_names:
        assert server.has_session(name)


# ============================================================================
# Server.ahas_session() Tests
# ============================================================================


@pytest.mark.asyncio
async def test_ahas_session(server: Server) -> None:
    """Test Server.ahas_session() checks session existence.

    Safety: All operations in isolated test server.
    Demonstrates: Async session existence check.
    """
    # Create a session first
    session = await server.anew_session("test_has_session")

    # Verify ahas_session returns True for existing session
    assert await server.ahas_session("test_has_session") is True

    # Verify ahas_session returns False for non-existent session
    assert await server.ahas_session("nonexistent_session_xyz") is False

    # Verify exact=True works with session ID
    session_id = session.session_id
    assert session_id is not None
    assert await server.ahas_session(session_id, exact=True) is True


@pytest.mark.asyncio
async def test_ahas_session_concurrent_checks(server: Server) -> None:
    """Test checking multiple sessions concurrently via ahas_session().

    Safety: All sessions created/checked in isolated test server.
    Demonstrates: Async benefit - parallel existence checks.
    """
    # Create 3 sessions
    await asyncio.gather(
        server.anew_session("check_a"),
        server.anew_session("check_b"),
        server.anew_session("check_c"),
    )

    # Check all sessions concurrently
    results = await asyncio.gather(
        server.ahas_session("check_a"),
        server.ahas_session("check_b"),
        server.ahas_session("check_c"),
        server.ahas_session("nonexistent"),
    )

    # Verify results
    assert results[0] is True  # check_a exists
    assert results[1] is True  # check_b exists
    assert results[2] is True  # check_c exists
    assert results[3] is False  # nonexistent doesn't exist
