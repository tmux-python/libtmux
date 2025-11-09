"""Tests for libtmux async operations.

SAFETY: All tests use isolated test servers via fixtures.
Socket names: libtmux_test{8_random_chars} - never affects developer sessions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from libtmux.session import Session

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
    assert result.returncode in (0, 1)
    assert isinstance(result.stdout, list)
    assert isinstance(result.stderr, list)


@pytest.mark.asyncio
async def test_server_acmd_new_session(server: Server) -> None:
    """Test creating session via Server.acmd().

    Safety: Session created in isolated test server only.
    """
    result = await server.acmd("new-session", "-d", "-P", "-F#{session_id}")
    session_id = result.stdout[0]

    try:
        # Verify session was created
        assert session_id.startswith("$")
        assert server.has_session(session_id)

        # Verify we can get the session object
        session = Session.from_session_id(session_id=session_id, server=server)
        assert isinstance(session, Session)
        assert session.session_id == session_id

    finally:
        # Cleanup: kill the session we created
        if server.has_session(session_id):
            session = Session.from_session_id(session_id=session_id, server=server)
            await session.acmd("kill-session")


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
