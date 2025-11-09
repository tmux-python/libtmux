"""Tests for Window async operations.

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
# Concurrent Operations Tests
# ============================================================================


@pytest.mark.asyncio
async def test_concurrent_pane_splits(session: Session) -> None:
    """Test splitting window into multiple panes concurrently.

    Safety: All panes created in isolated test window.
    Demonstrates creating a multi-pane layout efficiently.
    """
    import asyncio

    window = session.active_window
    assert window is not None

    async def split_pane(direction: str) -> str:
        """Split the window and return new pane ID."""
        result = await window.acmd(
            "split-window",
            direction,
            "-P",
            "-F#{pane_id}",
        )
        return result.stdout[0]

    # Create a 2x2 grid: split horizontally then split each half vertically
    # First split horizontally
    pane1 = await split_pane("-h")

    # Now split both panes vertically in parallel
    pane2, pane3 = await asyncio.gather(
        split_pane("-v"),
        split_pane("-v"),
    )

    # Verify we now have 4 panes (1 original + 3 created)
    result = await window.acmd("list-panes", "-F#{pane_id}")
    assert len(result.stdout) == 4

    # Verify all created panes exist
    pane_ids = result.stdout
    assert pane1 in pane_ids
    assert pane2 in pane_ids
    assert pane3 in pane_ids


@pytest.mark.asyncio
async def test_parallel_pane_queries(session: Session) -> None:
    """Test querying multiple panes concurrently.

    Safety: All operations in isolated test window.
    Real-world pattern: Monitor multiple panes efficiently.
    """
    import asyncio

    window = session.active_window
    assert window is not None

    # Create 3 panes (1 original + 2 splits)
    await window.acmd("split-window", "-h")
    await window.acmd("split-window", "-v")

    # Get all pane IDs
    result = await window.acmd("list-panes", "-F#{pane_id}")
    pane_ids = result.stdout
    assert len(pane_ids) == 3

    async def get_pane_info(pane_id: str) -> dict[str, str]:
        """Get pane dimensions and active status."""
        result = await window.acmd(
            "display-message",
            "-t",
            pane_id,
            "-p",
            "#{pane_id}:#{pane_width}:#{pane_height}:#{pane_active}",
        )
        output = result.stdout[0]
        parts = output.split(":")
        return {
            "id": parts[0],
            "width": parts[1],
            "height": parts[2],
            "active": parts[3],
        }

    # Query all panes concurrently
    pane_infos = await asyncio.gather(*[get_pane_info(pid) for pid in pane_ids])

    # Verify all queries succeeded
    assert len(pane_infos) == 3
    for info in pane_infos:
        assert info["id"].startswith("%")
        assert int(info["width"]) > 0
        assert int(info["height"]) > 0
        assert info["active"] in {"0", "1"}


# ============================================================================
# Window.akill() Tests
# ============================================================================


@pytest.mark.asyncio
async def test_akill_basic(session: Session) -> None:
    """Test Window.akill() kills window.

    Safety: Windows created and killed in isolated test session.
    Demonstrates: High-level async window destruction API.
    """
    # Create 2 windows (session starts with 1)
    window1 = await session.anew_window("window_to_kill")
    window2 = await session.anew_window("window_to_keep")

    # Get window count before kill
    result = await session.acmd("list-windows", "-F#{window_id}")
    windows_before = len(result.stdout)
    assert windows_before == 3  # original + 2 new

    # Kill window1
    await window1.akill()

    # Verify window1 is gone
    result = await session.acmd("list-windows", "-F#{window_id}")
    windows_after = len(result.stdout)
    assert windows_after == windows_before - 1
    assert window1.window_id not in result.stdout
    assert window2.window_id in result.stdout


@pytest.mark.asyncio
async def test_akill_all_except(session: Session) -> None:
    """Test Window.akill() with all_except flag.

    Safety: Windows created and killed in isolated test session.
    Real-world pattern: Clean up all windows except current one.
    """
    # Create 4 additional windows (session starts with 1)
    await session.anew_window("extra_1")
    await session.anew_window("extra_2")
    await session.anew_window("extra_3")
    target_window = await session.anew_window("target_window")

    # Get window count before kill
    result = await session.acmd("list-windows", "-F#{window_id}")
    windows_before = len(result.stdout)
    assert windows_before == 5  # original + 4 new

    # Kill all windows except target_window
    await target_window.akill(all_except=True)

    # Verify only target_window remains
    result = await session.acmd("list-windows", "-F#{window_id}")
    windows_after = result.stdout
    assert len(windows_after) == 1
    assert windows_after[0] == target_window.window_id
