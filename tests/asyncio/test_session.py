"""Tests for Session async operations.

SAFETY: All tests use isolated test servers via fixtures.
Socket names: libtmux_test{8_random_chars} - never affects developer sessions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from libtmux.session import Session

logger = logging.getLogger(__name__)


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
# Concurrent Operations Tests
# ============================================================================


@pytest.mark.asyncio
async def test_concurrent_window_creation(session: Session) -> None:
    """Test creating multiple windows concurrently in same session.

    Safety: All windows created in isolated test session.
    Demonstrates async benefit: parallel window creation.
    """
    import asyncio

    async def create_window(name: str) -> str:
        """Create a window and return its ID."""
        result = await session.acmd(
            "new-window",
            "-P",
            "-F#{window_id}",
            "-n",
            name,
        )
        return result.stdout[0]

    # Create 4 windows concurrently
    window_ids = await asyncio.gather(
        create_window("editor"),
        create_window("terminal"),
        create_window("logs"),
        create_window("monitor"),
    )

    # Verify all windows were created
    assert len(window_ids) == 4
    assert all(wid.startswith("@") for wid in window_ids)
    assert len(set(window_ids)) == 4  # All unique

    # Verify windows exist in session
    result = await session.acmd("list-windows", "-F#{window_id}")
    for window_id in window_ids:
        assert window_id in result.stdout


@pytest.mark.asyncio
async def test_parallel_window_queries(session: Session) -> None:
    """Test querying window properties concurrently.

    Safety: All operations in isolated test session.
    Real-world pattern: Gather window information efficiently.
    """
    import asyncio

    # Create a few windows first
    for i in range(3):
        await session.acmd("new-window", "-n", f"win_{i}")

    # Get all window IDs
    result = await session.acmd("list-windows", "-F#{window_id}")
    window_ids = result.stdout

    async def get_window_info(window_id: str) -> dict[str, str]:
        """Get window name and pane count."""
        result = await session.acmd(
            "display-message",
            "-t",
            window_id,
            "-p",
            "#{window_id}:#{window_name}:#{window_panes}",
        )
        output = result.stdout[0]
        parts = output.split(":")
        return {
            "id": parts[0],
            "name": parts[1],
            "panes": parts[2],
        }

    # Query all windows concurrently
    window_infos = await asyncio.gather(*[get_window_info(wid) for wid in window_ids])

    # Verify all queries succeeded
    assert len(window_infos) >= 3
    for info in window_infos:
        assert info["id"].startswith("@")
        assert int(info["panes"]) >= 1
