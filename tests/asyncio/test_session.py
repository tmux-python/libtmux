"""Tests for Session async operations.

SAFETY: All tests use isolated test servers via fixtures.
Socket names: libtmux_test{8_random_chars} - never affects developer sessions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from libtmux.session import Session


@dataclass(slots=True)
class WindowInfo:
    """Minimal window details fetched concurrently during tests."""

    id: str
    name: str
    panes: int


@dataclass(slots=True)
class ProjectSessionStatus:
    """Summary of session setup used for verification."""

    session_id: str
    name: str
    window_count: int


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

    async def get_window_info(window_id: str) -> WindowInfo:
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
        return WindowInfo(id=parts[0], name=parts[1], panes=int(parts[2]))

    # Query all windows concurrently
    window_infos: list[WindowInfo] = await asyncio.gather(
        *[get_window_info(wid) for wid in window_ids]
    )

    # Verify all queries succeeded
    assert len(window_infos) >= 3
    for info in window_infos:
        assert info.id.startswith("@")
        assert info.panes >= 1


# ============================================================================
# Session.anew_window() Tests
# ============================================================================


@pytest.mark.asyncio
async def test_anew_window_basic(session: Session) -> None:
    """Test Session.anew_window() creates window.

    Safety: Window created in isolated test session.
    Demonstrates: High-level async window creation API.
    """
    from libtmux.window import Window

    # Get initial window count
    initial_result = await session.acmd("list-windows", "-F#{window_id}")
    initial_count = len(initial_result.stdout)

    # Create new window using anew_window()
    window = await session.anew_window("test_window")

    # Verify window created with correct properties
    assert isinstance(window, Window)
    window_id = window.window_id
    assert window_id is not None
    assert window_id.startswith("@")

    # Verify window was added to session
    result = await session.acmd("list-windows", "-F#{window_id}")
    assert len(result.stdout) == initial_count + 1
    assert window_id in result.stdout


@pytest.mark.asyncio
async def test_anew_window_with_directory(session: Session) -> None:
    """Test Session.anew_window() with start_directory.

    Safety: Window created in isolated test session.
    Real-world pattern: Create window in specific working directory.
    """
    import asyncio
    from pathlib import Path

    from libtmux.window import Window

    # Use /tmp as start directory
    start_dir = Path("/tmp")

    window = await session.anew_window(
        "dir_window",
        start_directory=start_dir,
    )

    # Verify window created
    assert isinstance(window, Window)

    # Verify working directory by sending pwd command
    pane = window.active_pane
    assert pane is not None

    # Clear pane first to ensure clean output
    await pane.acmd("send-keys", "clear", "Enter")
    await asyncio.sleep(0.1)

    # Send pwd command
    await pane.acmd("send-keys", "pwd", "Enter")
    await asyncio.sleep(0.3)

    # Capture output
    result = await pane.acmd("capture-pane", "-p", "-S", "-")
    # Check if /tmp appears in any line of output
    output_text = "\n".join(result.stdout)
    assert "/tmp" in output_text, f"Expected /tmp in output, got: {output_text}"


@pytest.mark.asyncio
async def test_anew_window_concurrent(session: Session) -> None:
    """Test creating multiple windows concurrently via anew_window().

    Safety: All windows created in isolated test session.
    Demonstrates: Async benefit - concurrent high-level window creation.
    """
    import asyncio

    from libtmux.window import Window

    async def create_window(name: str) -> Window:
        """Create window using anew_window()."""
        return await session.anew_window(name)

    # Create 4 windows concurrently
    windows = await asyncio.gather(
        create_window("window_1"),
        create_window("window_2"),
        create_window("window_3"),
        create_window("window_4"),
    )

    # Verify all windows created
    assert len(windows) == 4
    assert all(isinstance(w, Window) for w in windows)

    # Verify all have unique IDs
    window_ids: set[str] = set()
    for window in windows:
        assert window.window_id is not None
        window_ids.add(window.window_id)
    assert len(window_ids) == 4

    # Verify all exist in session
    result = await session.acmd("list-windows", "-F#{window_id}")
    for window_id in window_ids:
        assert window_id in result.stdout


# ============================================================================
# Session.arename_session() Tests
# ============================================================================


@pytest.mark.asyncio
async def test_arename_session(session: Session) -> None:
    """Test Session.arename_session() renames session.

    Safety: Session renamed in isolated test server.
    Demonstrates: High-level async session rename API.
    """
    # Get original name
    original_name = session.session_name
    assert original_name is not None

    # Rename session
    new_name = "renamed_async_session"
    result_session = await session.arename_session(new_name)

    # Verify return value is the session object
    assert result_session is session

    # Verify session was renamed
    session.refresh()
    current_name = session.session_name
    assert current_name is not None
    assert current_name == new_name

    # Verify old name is gone, new name exists
    assert not session.server.has_session(original_name)
    assert session.server.has_session(new_name)
