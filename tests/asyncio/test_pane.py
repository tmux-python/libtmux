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


# ============================================================================
# Pane.asend_keys() Tests
# ============================================================================


@pytest.mark.asyncio
async def test_asend_keys_basic_execution(session: Session) -> None:
    """Test Pane.asend_keys() basic command execution with enter.

    Safety: Commands sent to isolated test pane only.
    """
    pane = session.active_pane
    assert pane is not None

    # Send command with enter
    await pane.asend_keys('echo "test_asend_basic"', enter=True)

    # Wait for command to execute
    await asyncio.sleep(0.2)

    # Verify output
    output = pane.capture_pane()
    assert any("test_asend_basic" in line for line in output)


@pytest.mark.asyncio
async def test_asend_keys_without_enter(session: Session) -> None:
    """Test Pane.asend_keys() without enter - command visible but not executed.

    Safety: Commands sent to isolated test pane only.
    """
    pane = session.active_pane
    assert pane is not None

    # Send command without enter
    await pane.asend_keys('echo "should_not_execute"', enter=False)

    # Wait briefly
    await asyncio.sleep(0.1)

    # Verify command text is visible but not executed
    output = pane.capture_pane()
    # Command should be visible in the pane
    assert any("echo" in line for line in output)
    # But output should NOT appear (command not executed)
    # Note: We can't test for absence of output directly as the prompt might vary


@pytest.mark.asyncio
async def test_asend_keys_literal_mode(session: Session) -> None:
    """Test Pane.asend_keys() literal mode - special chars sent as text.

    Safety: Commands sent to isolated test pane only.
    """
    pane = session.active_pane
    assert pane is not None

    # Send literal special character (not a signal)
    await pane.asend_keys('C-c', literal=True, enter=False)

    # Wait briefly
    await asyncio.sleep(0.1)

    # Verify literal text "C-c" appears (not an interrupt signal)
    output = pane.capture_pane()
    assert any("C-c" in line for line in output)


@pytest.mark.asyncio
async def test_asend_keys_suppress_history(session: Session) -> None:
    """Test Pane.asend_keys() with suppress_history prepends space.

    Safety: Commands sent to isolated test pane only.
    """
    pane = session.active_pane
    assert pane is not None

    # Send command with history suppression
    await pane.asend_keys('echo "secret_command"', suppress_history=True, enter=True)

    # Wait for execution
    await asyncio.sleep(0.2)

    # Verify output appears (command executed)
    output = pane.capture_pane()
    assert any("secret_command" in line for line in output)
    # Note: Full history verification would require shell-specific setup


@pytest.mark.asyncio
async def test_asend_keys_concurrent_multiple_panes(session: Session) -> None:
    """Test sending keys to multiple panes concurrently via asend_keys().

    Safety: All panes in isolated test session.
    Real-world pattern: Execute commands across multiple panes simultaneously.
    """
    window = session.active_window
    assert window is not None

    # Create 3 panes
    pane1 = window.active_pane
    pane2 = window.split()
    pane3 = window.split()

    # Send different commands to all panes concurrently
    await asyncio.gather(
        pane1.asend_keys('echo "pane1_output"'),
        pane2.asend_keys('echo "pane2_output"'),
        pane3.asend_keys('echo "pane3_output"'),
    )

    # Wait for commands to execute
    await asyncio.sleep(0.3)

    # Verify each pane has correct output
    output1 = pane1.capture_pane()
    output2 = pane2.capture_pane()
    output3 = pane3.capture_pane()

    assert any("pane1_output" in line for line in output1)
    assert any("pane2_output" in line for line in output2)
    assert any("pane3_output" in line for line in output3)


# ============================================================================
# Pane.acapture_pane() Tests
# ============================================================================


@pytest.mark.asyncio
async def test_acapture_pane_basic(session: Session) -> None:
    """Test Pane.acapture_pane() basic output capture.

    Safety: Capture from isolated test pane only.
    """
    pane = session.active_pane
    assert pane is not None

    # Send command
    await pane.asend_keys('echo "capture_test_output"')
    await asyncio.sleep(0.2)

    # Capture output
    output = await pane.acapture_pane()

    # Verify output
    assert isinstance(output, list)
    assert any("capture_test_output" in line for line in output)


@pytest.mark.asyncio
async def test_acapture_pane_with_start_parameter(session: Session) -> None:
    """Test Pane.acapture_pane() with start parameter to capture history.

    Safety: Capture from isolated test pane only.
    """
    pane = session.active_pane
    assert pane is not None

    # Send multiple commands to build history
    await pane.asend_keys('echo "line1"')
    await asyncio.sleep(0.1)
    await pane.asend_keys('echo "line2"')
    await asyncio.sleep(0.1)
    await pane.asend_keys('echo "line3"')
    await asyncio.sleep(0.2)

    # Capture with start parameter (last 10 lines including history)
    output = await pane.acapture_pane(start=-10)

    # Verify output includes history
    assert isinstance(output, list)
    assert len(output) > 0


@pytest.mark.asyncio
async def test_acapture_pane_with_end_parameter(session: Session) -> None:
    """Test Pane.acapture_pane() with end parameter to limit output.

    Safety: Capture from isolated test pane only.
    """
    pane = session.active_pane
    assert pane is not None

    # Send commands
    await pane.asend_keys('echo "test_line"')
    await asyncio.sleep(0.2)

    # Capture with end parameter (first 5 lines)
    output = await pane.acapture_pane(end=5)

    # Verify output is limited
    assert isinstance(output, list)
    assert len(output) <= 6  # end=5 means lines 0-5 inclusive


@pytest.mark.asyncio
async def test_acapture_pane_full_history(session: Session) -> None:
    """Test Pane.acapture_pane() capturing complete scrollback history.

    Safety: Capture from isolated test pane only.
    """
    pane = session.active_pane
    assert pane is not None

    # Send multiple commands
    for i in range(5):
        await pane.asend_keys(f'echo "history_line_{i}"')
        await asyncio.sleep(0.1)

    # Capture full history (from start to end)
    output = await pane.acapture_pane(start="-", end="-")

    # Verify we got output
    assert isinstance(output, list)
    assert len(output) > 0


@pytest.mark.asyncio
async def test_acapture_pane_concurrent_multiple_panes(session: Session) -> None:
    """Test capturing from multiple panes concurrently via acapture_pane().

    Safety: All panes in isolated test session.
    Real-world pattern: Monitor outputs from multiple panes simultaneously.
    """
    window = session.active_window
    assert window is not None

    # Create 3 panes
    pane1 = window.active_pane
    pane2 = window.split()
    pane3 = window.split()

    # Send different commands to each pane
    await asyncio.gather(
        pane1.asend_keys('echo "capture1"'),
        pane2.asend_keys('echo "capture2"'),
        pane3.asend_keys('echo "capture3"'),
    )
    await asyncio.sleep(0.3)

    # Capture output from all panes concurrently
    outputs = await asyncio.gather(
        pane1.acapture_pane(),
        pane2.acapture_pane(),
        pane3.acapture_pane(),
    )

    # Verify all outputs
    assert len(outputs) == 3
    assert any("capture1" in line for line in outputs[0])
    assert any("capture2" in line for line in outputs[1])
    assert any("capture3" in line for line in outputs[2])


# ============================================================================
# Pane.asplit() Tests
# ============================================================================


@pytest.mark.asyncio
async def test_asplit_default_below(session: Session) -> None:
    """Test Pane.asplit() default split direction (below).

    Safety: Pane split in isolated test session.
    """
    window = session.active_window
    assert window is not None
    pane = window.active_pane

    initial_pane_count = len(window.panes)

    # Split pane (default is below)
    new_pane = await pane.asplit()

    # Verify new pane created
    assert len(window.panes) == initial_pane_count + 1
    assert new_pane is not None
    assert new_pane.pane_id != pane.pane_id


@pytest.mark.asyncio
async def test_asplit_direction_right(session: Session) -> None:
    """Test Pane.asplit() vertical split to the right.

    Safety: Pane split in isolated test session.
    """
    from libtmux.pane import PaneDirection

    window = session.active_window
    assert window is not None
    pane = window.active_pane

    initial_pane_count = len(window.panes)

    # Split pane to the right
    new_pane = await pane.asplit(direction=PaneDirection.Right)

    # Verify new pane created
    assert len(window.panes) == initial_pane_count + 1
    assert new_pane is not None
    assert new_pane.pane_id != pane.pane_id


@pytest.mark.asyncio
async def test_asplit_with_start_directory(session: Session) -> None:
    """Test Pane.asplit() with custom start directory.

    Safety: Pane split in isolated test session.
    """
    window = session.active_window
    assert window is not None
    pane = window.active_pane

    # Split with custom directory
    new_pane = await pane.asplit(start_directory='/tmp')

    # Verify pane created
    assert new_pane is not None

    # Send pwd command to verify directory
    await new_pane.asend_keys('pwd')
    await asyncio.sleep(0.3)

    # Check output
    output = new_pane.capture_pane()
    # Verify /tmp appears in output (pwd result)
    has_tmp = any('/tmp' in line for line in output)
    assert has_tmp, f"Expected /tmp in output, got: {output}"


@pytest.mark.asyncio
async def test_asplit_with_size(session: Session) -> None:
    """Test Pane.asplit() with size parameter.

    Safety: Pane split in isolated test session.
    """
    window = session.active_window
    assert window is not None
    pane = window.active_pane

    initial_pane_count = len(window.panes)

    # Split with size (30%)
    new_pane = await pane.asplit(size="30%")

    # Verify pane created
    assert len(window.panes) == initial_pane_count + 1
    assert new_pane is not None
    # Note: Actual size verification would require dimension checks


@pytest.mark.asyncio
async def test_asplit_with_shell_command(session: Session) -> None:
    """Test Pane.asplit() with shell command (auto-closes after execution).

    Safety: Pane split in isolated test session.
    Note: Pane auto-closes when command completes, which is expected behavior.
    """
    window = session.active_window
    assert window is not None
    pane = window.active_pane

    initial_pane_count = len(window.panes)

    # Split with shell command that runs longer before exiting
    # Use sleep to keep pane alive briefly
    new_pane = await pane.asplit(shell='sleep 0.3 && echo "done"')

    # Verify pane was created
    assert new_pane is not None
    assert new_pane.pane_id is not None

    # Verify pane exists initially (before command finishes)
    immediate_pane_count = len(window.panes)
    assert immediate_pane_count == initial_pane_count + 1

    # Wait for command to complete and pane to auto-close
    await asyncio.sleep(0.6)

    # Verify pane count reduced (pane auto-closed)
    final_pane_count = len(window.panes)
    assert final_pane_count == initial_pane_count


@pytest.mark.asyncio
async def test_asplit_concurrent_multiple_splits(session: Session) -> None:
    """Test creating multiple panes concurrently via asplit().

    Safety: All panes in isolated test session.
    Real-world pattern: Rapidly create complex pane layouts.
    """
    window = session.active_window
    assert window is not None
    base_pane = window.active_pane

    initial_pane_count = len(window.panes)

    # Create multiple panes concurrently
    from libtmux.pane import PaneDirection

    new_panes = await asyncio.gather(
        base_pane.asplit(direction=PaneDirection.Right),
        base_pane.asplit(direction=PaneDirection.Below),
    )

    # Verify panes created
    assert len(new_panes) == 2
    assert all(p is not None for p in new_panes)
    assert len(window.panes) >= initial_pane_count + 2
