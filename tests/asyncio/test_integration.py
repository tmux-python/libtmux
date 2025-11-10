"""Integration tests for complex async workflows.

SAFETY: All tests use isolated test servers via fixtures.
Socket names: libtmux_test{8_random_chars} - never affects developer sessions.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import pytest

from libtmux.pane import Pane
from libtmux.session import Session
from libtmux.window import Window

if TYPE_CHECKING:
    from libtmux.server import Server

logger = logging.getLogger(__name__)


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_async_full_workflow(server: Server) -> None:
    """Test complete async workflow: session -> window -> pane -> command.

    Safety: All objects created in isolated test server.
    Demonstrates comprehensive async tmux manipulation.
    Cleanup: Server fixture finalizer handles all resource destruction.
    """
    # Create session
    result = await server.acmd("new-session", "-d", "-P", "-F#{session_id}")
    session_id = result.stdout[0]
    session = Session.from_session_id(session_id=session_id, server=server)

    # Verify session created
    assert session_id.startswith("$")
    assert server.has_session(session_id)

    # Create window in session
    result = await session.acmd("new-window", "-P", "-F#{window_id}")
    window_id = result.stdout[0]
    window = Window.from_window_id(window_id=window_id, server=server)
    assert window_id.startswith("@")

    # Split pane in window
    result = await window.acmd("split-window", "-P", "-F#{pane_id}")
    pane_id = result.stdout[0]
    pane = Pane.from_pane_id(pane_id=pane_id, server=server)
    assert pane_id.startswith("%")

    # Send command to pane
    await pane.acmd("send-keys", "echo 'integration_test_complete'", "Enter")
    await asyncio.sleep(0.2)

    # Verify output
    result = await pane.acmd("capture-pane", "-p")
    assert any("integration_test_complete" in line for line in result.stdout)

    # Verify complete object hierarchy
    assert session.session_id == session_id
    assert window.window_id == window_id
    assert pane.pane_id == pane_id


@pytest.mark.asyncio
async def test_multi_session_parallel_automation(server: Server) -> None:
    """Test automating multiple sessions concurrently.

    Safety: All sessions created in isolated test server.
    Real-world pattern: Set up multiple project environments simultaneously.
    """

    async def setup_project_session(
        name: str, num_windows: int
    ) -> dict[str, str | int]:
        """Create session with multiple windows."""
        # Create session
        result = await server.acmd(
            "new-session",
            "-d",
            "-P",
            "-F#{session_id}",
            "-s",
            name,
        )
        session_id = result.stdout[0]
        session = Session.from_session_id(session_id=session_id, server=server)

        # Create additional windows concurrently
        window_tasks = [
            session.acmd("new-window", "-P", "-F#{window_id}", "-n", f"win_{i}")
            for i in range(num_windows - 1)  # -1 because session starts with 1 window
        ]
        await asyncio.gather(*window_tasks)

        # Verify setup
        result = await session.acmd("list-windows", "-F#{window_id}")
        window_count = len(result.stdout)

        return {
            "session_id": session_id,
            "name": name,
            "window_count": window_count,
        }

    # Set up 3 project sessions concurrently
    results = await asyncio.gather(
        setup_project_session("project_frontend", 3),
        setup_project_session("project_backend", 4),
        setup_project_session("project_infra", 2),
    )

    # Verify all sessions set up correctly
    assert len(results) == 3
    assert results[0]["window_count"] == 3
    assert results[1]["window_count"] == 4
    assert results[2]["window_count"] == 2

    # Verify all sessions exist
    for result in results:
        assert server.has_session(result["name"])


@pytest.mark.asyncio
async def test_complex_pane_grid_automation(server: Server) -> None:
    """Test creating and configuring a complex pane grid.

    Safety: All operations in isolated test server.
    Real-world pattern: Dashboard layout with multiple monitoring panes.
    """
    # Create session
    result = await server.acmd("new-session", "-d", "-P", "-F#{session_id}")
    session_id = result.stdout[0]
    session = Session.from_session_id(session_id=session_id, server=server)

    window = session.active_window
    assert window is not None

    # Create a 2x3 grid of panes
    # Split into 2 columns
    await window.acmd("split-window", "-h")

    # Split each column into 3 rows concurrently
    await asyncio.gather(
        window.acmd("split-window", "-v"),
        window.acmd("split-window", "-v"),
        window.acmd("split-window", "-v", "-t", "{right}"),
        window.acmd("split-window", "-v", "-t", "{right}"),
    )

    # Get all pane IDs
    result = await window.acmd("list-panes", "-F#{pane_id}")
    pane_ids = result.stdout
    assert len(pane_ids) == 6  # 2x3 grid

    # Configure each pane with a different "monitoring" command concurrently
    monitoring_commands = [
        "echo 'CPU Monitor'",
        "echo 'Memory Monitor'",
        "echo 'Disk Monitor'",
        "echo 'Network Monitor'",
        "echo 'Process Monitor'",
        "echo 'Log Monitor'",
    ]

    async def configure_pane(pane_id: str, command: str) -> str:
        """Send command to pane."""
        pane = Pane.from_pane_id(pane_id=pane_id, server=server)
        await pane.acmd("send-keys", command, "Enter")
        return pane_id

    # Configure all panes concurrently
    await asyncio.gather(
        *[
            configure_pane(pid, cmd)
            for pid, cmd in zip(pane_ids, monitoring_commands, strict=False)
        ]
    )

    await asyncio.sleep(0.3)

    # Verify all panes configured
    expected_texts = ["CPU", "Memory", "Disk", "Network", "Process", "Log"]
    for pane_id, expected in zip(pane_ids, expected_texts, strict=False):
        pane = Pane.from_pane_id(pane_id=pane_id, server=server)
        result = await pane.acmd("capture-pane", "-p")
        assert any(expected in line for line in result.stdout), f"{expected} not found"


# ============================================================================
# Error Handling & Edge Cases
# ============================================================================


@pytest.mark.asyncio
async def test_concurrent_operations_with_partial_failure(server: Server) -> None:
    """Test handling partial failures in concurrent operations.

    Safety: All operations in isolated test server.
    Demonstrates error handling: some operations succeed, some fail.
    """

    async def create_session_safe(name: str) -> tuple[str, bool, str]:
        """Create session and return status."""
        try:
            result = await server.acmd(
                "new-session",
                "-d",
                "-P",
                "-F#{session_id}",
                "-s",
                name,
            )
        except Exception as e:
            return (name, False, str(e))
        else:
            session_id = result.stdout[0] if result.stdout else ""
            success = result.returncode == 0
            return (name, success, session_id)

    # Create sessions, including one duplicate (will fail)
    results = await asyncio.gather(
        create_session_safe("valid_session_1"),
        create_session_safe("valid_session_2"),
        create_session_safe("valid_session_1"),  # Duplicate - should fail
        create_session_safe("valid_session_3"),
    )

    # Verify we got 4 results
    assert len(results) == 4

    # Check successes and failures
    successes = [r for r in results if r[1]]
    failures = [r for r in results if not r[1]]

    # Should have 3 successes and 1 failure (duplicate)
    assert len(successes) == 3
    assert len(failures) == 1
    assert failures[0][0] == "valid_session_1"  # Duplicate name


@pytest.mark.asyncio
async def test_async_command_timeout_handling(server: Server) -> None:
    """Test handling slow/hanging commands.

    Safety: All operations in isolated test server.
    Demonstrates: async timeout patterns for command execution.
    """

    async def create_session_with_timeout(
        name: str, timeout: float
    ) -> tuple[str, bool]:
        """Create session with timeout."""
        try:
            await asyncio.wait_for(
                server.acmd("new-session", "-d", "-P", "-F#{session_id}", "-s", name),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return (name, False)
        else:
            return (name, True)

    # Create sessions with generous timeout (should all succeed)
    results = await asyncio.gather(
        create_session_with_timeout("session_1", 5.0),
        create_session_with_timeout("session_2", 5.0),
        create_session_with_timeout("session_3", 5.0),
    )

    # All should succeed with reasonable timeout
    assert len(results) == 3
    assert all(success for _, success in results)


# ============================================================================
# Async Pane Method Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_async_pane_workflow_complete(server: Server) -> None:
    """Test complete pane lifecycle with new async methods.

    Safety: All operations in isolated test server.
    Demonstrates: Full async workflow using asend_keys, acapture_pane, asplit.
    Pattern: Create -> send -> capture -> split -> concurrent ops -> cleanup.
    """
    # Create session
    session = await server.anew_session("pane_workflow_test")

    # Get active pane
    pane1 = session.active_pane
    assert pane1 is not None

    # Send command using asend_keys
    await pane1.asend_keys('echo "workflow_step_1"')
    await asyncio.sleep(0.2)

    # Capture output using acapture_pane
    output1 = await pane1.acapture_pane()
    assert any("workflow_step_1" in line for line in output1)

    # Split pane using asplit
    pane2 = await pane1.asplit()
    assert pane2 is not None
    assert pane2.pane_id != pane1.pane_id

    # Verify both panes exist
    window = session.active_window
    assert len(window.panes) == 2

    # Send different commands to each pane concurrently
    await asyncio.gather(
        pane1.asend_keys('echo "pane1_data"'),
        pane2.asend_keys('echo "pane2_data"'),
    )
    await asyncio.sleep(0.3)

    # Capture outputs concurrently
    outputs = await asyncio.gather(
        pane1.acapture_pane(),
        pane2.acapture_pane(),
    )

    # Verify both outputs
    assert any("pane1_data" in line for line in outputs[0])
    assert any("pane2_data" in line for line in outputs[1])


@pytest.mark.asyncio
async def test_multi_window_pane_automation(server: Server) -> None:
    """Test complex multi-window, multi-pane async automation.

    Safety: All operations in isolated test server.
    Demonstrates: Large-scale concurrent pane manipulation.
    Pattern: 3 windows × 3 panes = 9 panes, all managed concurrently.
    """
    # Create session
    session = await server.anew_session("multi_window_automation")

    # Create 3 windows concurrently
    windows_data = await asyncio.gather(
        session.anew_window(window_name="window1"),
        session.anew_window(window_name="window2"),
        session.anew_window(window_name="window3"),
    )

    # Each window should have 1 pane initially
    all_panes = []

    # For each window, split into 3 panes total
    for i, window in enumerate(windows_data):
        base_pane = window.active_pane

        # Create 2 more panes (total 3 per window)
        from libtmux.pane import PaneDirection

        new_panes = await asyncio.gather(
            base_pane.asplit(direction=PaneDirection.Right),
            base_pane.asplit(direction=PaneDirection.Below),
        )

        # Collect all 3 panes from this window
        all_panes.extend([base_pane] + list(new_panes))

    # Verify we have 9 panes total (3 windows × 3 panes)
    assert len(all_panes) == 9

    # Send unique commands to all 9 panes concurrently
    send_tasks = [
        pane.asend_keys(f'echo "pane_{i}_output"')
        for i, pane in enumerate(all_panes)
    ]
    await asyncio.gather(*send_tasks)
    await asyncio.sleep(0.4)

    # Capture output from all 9 panes concurrently
    outputs = await asyncio.gather(
        *[pane.acapture_pane() for pane in all_panes]
    )

    # Verify all panes have correct output
    assert len(outputs) == 9
    for i, output in enumerate(outputs):
        assert any(f"pane_{i}_output" in line for line in output)


@pytest.mark.asyncio
async def test_pane_monitoring_dashboard(server: Server) -> None:
    """Test monitoring dashboard pattern with async pane methods.

    Safety: All operations in isolated test server.
    Demonstrates: Real-world monitoring use case with periodic capture.
    Pattern: 2x3 grid of panes, periodic concurrent monitoring.
    """
    # Create session
    session = await server.anew_session("monitoring_dashboard")
    window = session.active_window

    # Create 2x3 grid (6 panes total)
    # Start with 1 pane, split to make 6
    base_pane = window.active_pane

    from libtmux.pane import PaneDirection

    # Create top row (3 panes)
    pane2 = await base_pane.asplit(direction=PaneDirection.Right)
    pane3 = await base_pane.asplit(direction=PaneDirection.Right)

    # Create bottom row (3 more panes)
    pane4 = await base_pane.asplit(direction=PaneDirection.Below)
    pane5 = await pane2.asplit(direction=PaneDirection.Below)
    pane6 = await pane3.asplit(direction=PaneDirection.Below)

    all_panes = [base_pane, pane2, pane3, pane4, pane5, pane6]

    # Verify grid created
    assert len(window.panes) == 6

    # Send "monitoring" commands to each pane
    monitor_commands = [
        'echo "CPU: 45%"',
        'echo "Memory: 60%"',
        'echo "Disk: 30%"',
        'echo "Network: 100Mbps"',
        'echo "Processes: 150"',
        'echo "Uptime: 5 days"',
    ]

    await asyncio.gather(
        *[
            pane.asend_keys(cmd)
            for pane, cmd in zip(all_panes, monitor_commands, strict=False)
        ]
    )
    await asyncio.sleep(0.3)

    # Periodically capture all panes (simulate 3 monitoring rounds)
    for round_num in range(3):
        # Capture all panes concurrently
        outputs = await asyncio.gather(*[pane.acapture_pane() for pane in all_panes])

        # Verify all panes have output
        assert len(outputs) == 6

        # Verify specific monitoring data appears
        assert any("CPU:" in line for line in outputs[0])
        assert any("Memory:" in line for line in outputs[1])
        assert any("Disk:" in line for line in outputs[2])

        # Wait before next monitoring round
        if round_num < 2:
            await asyncio.sleep(0.2)

    # Verify dashboard functional after 3 rounds
    final_outputs = await asyncio.gather(*[pane.acapture_pane() for pane in all_panes])
    assert all(len(output) > 0 for output in final_outputs)
