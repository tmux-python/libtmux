"""Tests for Pane async operations.

SAFETY: All tests use isolated test servers via fixtures.
Socket names: libtmux_test{8_random_chars} - never affects developer sessions.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from libtmux.session import Session

logger = logging.getLogger(__name__)


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
# Real-World Automation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_concurrent_send_keys_multiple_panes(session: Session) -> None:
    """Test sending commands to multiple panes concurrently.

    Safety: All panes in isolated test session.
    Real-world pattern: Execute commands across multiple panes simultaneously.
    """
    from libtmux.pane import Pane

    window = session.active_window
    assert window is not None

    # Create 3 panes
    result1 = await window.acmd("split-window", "-h", "-P", "-F#{pane_id}")
    result2 = await window.acmd("split-window", "-v", "-P", "-F#{pane_id}")

    pane_ids = [
        session.active_pane.pane_id,
        result1.stdout[0],
        result2.stdout[0],
    ]

    async def send_command(pane_id: str, command: str) -> str:
        """Send command to pane and return pane ID."""
        pane = Pane.from_pane_id(pane_id=pane_id, server=session.server)
        await pane.acmd("send-keys", command, "Enter")
        return pane_id

    # Send different commands to all panes concurrently
    await asyncio.gather(
        send_command(pane_ids[0], "echo 'pane_0_output'"),
        send_command(pane_ids[1], "echo 'pane_1_output'"),
        send_command(pane_ids[2], "echo 'pane_2_output'"),
    )

    # Wait for commands to execute
    await asyncio.sleep(0.3)

    # Verify outputs from each pane
    async def check_output(pane_id: str, expected: str) -> bool:
        """Check if pane output contains expected string."""
        pane = Pane.from_pane_id(pane_id=pane_id, server=session.server)
        result = await pane.acmd("capture-pane", "-p")
        return any(expected in line for line in result.stdout)

    # Check all panes concurrently
    results = await asyncio.gather(
        check_output(pane_ids[0], "pane_0_output"),
        check_output(pane_ids[1], "pane_1_output"),
        check_output(pane_ids[2], "pane_2_output"),
    )

    assert all(results), "Not all panes executed commands successfully"


@pytest.mark.asyncio
async def test_batch_pane_setup_automation(session: Session) -> None:
    """Test setting up multiple panes with different commands.

    Safety: All operations in isolated test session.
    Real-world pattern: Initialize development environment with multiple services.
    """
    from libtmux.pane import Pane

    window = session.active_window
    assert window is not None

    # Define pane setup: command and check string
    pane_configs = [
        {"cmd": "echo 'Frontend: localhost:3000'", "check": "Frontend"},
        {"cmd": "echo 'Backend: localhost:8000'", "check": "Backend"},
        {"cmd": "echo 'Database: localhost:5432'", "check": "Database"},
    ]

    # Create panes
    pane_ids = [session.active_pane.pane_id]
    for _ in range(2):
        result = await window.acmd("split-window", "-h", "-P", "-F#{pane_id}")
        pane_ids.append(result.stdout[0])

    async def setup_pane(pane_id: str, config: dict[str, str]) -> dict[str, str | bool]:
        """Set up a pane with command and verify output."""
        pane = Pane.from_pane_id(pane_id=pane_id, server=session.server)

        # Send command
        await pane.acmd("send-keys", config["cmd"], "Enter")
        await asyncio.sleep(0.2)

        # Capture and verify
        result = await pane.acmd("capture-pane", "-p")
        success = any(config["check"] in line for line in result.stdout)

        return {
            "pane_id": pane_id,
            "command": config["cmd"],
            "success": success,
        }

    # Set up all panes concurrently
    results = await asyncio.gather(
        *[
            setup_pane(pid, config)
            for pid, config in zip(pane_ids, pane_configs, strict=False)
        ]
    )

    # Verify all setups succeeded
    assert len(results) == 3
    for result in results:
        assert result["success"], f"Pane {result['pane_id']} setup failed"


@pytest.mark.asyncio
async def test_parallel_pane_monitoring(session: Session) -> None:
    """Test monitoring output from multiple panes concurrently.

    Safety: All panes in isolated test session.
    Real-world pattern: Monitor logs from multiple services simultaneously.
    """
    from libtmux.pane import Pane

    window = session.active_window
    assert window is not None

    # Create 3 panes (original + 2 splits)
    result1 = await window.acmd("split-window", "-h", "-P", "-F#{pane_id}")
    result2 = await window.acmd("split-window", "-v", "-P", "-F#{pane_id}")

    pane_ids = [
        session.active_pane.pane_id,
        result1.stdout[0],
        result2.stdout[0],
    ]

    async def send_and_verify(pane_id: str, service_num: int) -> dict[str, str | bool]:
        """Send command to pane and verify output."""
        pane = Pane.from_pane_id(pane_id=pane_id, server=session.server)

        # Send command
        await pane.acmd("send-keys", f"echo 'service_{service_num}_running'", "Enter")
        await asyncio.sleep(0.3)

        # Capture and verify
        result = await pane.acmd("capture-pane", "-p")
        found = any(f"service_{service_num}_running" in line for line in result.stdout)

        return {
            "pane_id": pane_id,
            "service": f"service_{service_num}",
            "running": found,
        }

    # Send commands and monitor all panes concurrently
    monitor_results = await asyncio.gather(
        *[send_and_verify(pid, i) for i, pid in enumerate(pane_ids)]
    )

    # Verify all services detected
    assert len(monitor_results) == 3
    for result in monitor_results:
        assert result["running"], f"Service {result['service']} not detected"
