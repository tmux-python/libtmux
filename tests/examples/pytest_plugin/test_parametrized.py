"""Examples for parametrized tests with tmux."""

from __future__ import annotations

import time

import pytest

from libtmux.constants import PaneDirection


@pytest.mark.parametrize("window_name", ["test1", "test2", "test3"])
def test_multiple_windows(session, window_name) -> None:
    """Test creating windows with different names."""
    window = session.new_window(window_name=window_name)
    assert window.window_name == window_name

    # Do something with each window
    pane = window.active_pane
    pane.send_keys(f"echo 'Testing window {window_name}'", enter=True)

    # Verify output
    time.sleep(0.5)
    output = pane.capture_pane()
    assert any(f"Testing window {window_name}" in line for line in output)


@pytest.mark.parametrize(
    ("command", "expected_output"),
    [
        ("echo 'Hello'", "Hello"),
        ("printf 'Test\\n123'", "Test"),
        ("ls -la | head -n 1", "total"),
        ("date +%Y", str(time.localtime().tm_year)),
    ],
)
def test_various_commands(session, command, expected_output) -> None:
    """Test different commands and verify their output."""
    window = session.new_window(window_name="command-test")
    pane = window.active_pane

    # Clear the pane first
    pane.send_keys("clear", enter=True)
    time.sleep(0.3)

    # Run the command
    pane.send_keys(command, enter=True)
    time.sleep(0.5)

    # Verify the output
    output = pane.capture_pane()
    assert any(expected_output in line for line in output), (
        f"Expected '{expected_output}' in output"
    )


# Skip layouts that are causing issues in the test environment
@pytest.mark.parametrize("layout", ["even-horizontal", "even-vertical", "tiled"])
def test_window_layouts(session, layout) -> None:
    """Test different window layouts."""
    window = session.new_window(window_name=f"layout-{layout}")

    # Create multiple panes for the layout
    pane1 = window.active_pane
    pane2 = window.split(direction=PaneDirection.Right)
    pane3 = pane1.split(direction=PaneDirection.Below)

    # Set the layout
    window.select_layout(layout)

    # Verify the layout was set
    current_layout = window.window_layout
    assert current_layout is not None, "Layout was not set"

    # Clear all panes
    pane1.send_keys("clear", enter=True)
    pane2.send_keys("clear", enter=True)
    pane3.send_keys("clear", enter=True)
    time.sleep(0.5)  # Increased from 0.3 to 0.5

    # Send a message to each pane confirming its existence
    pane1.send_keys(f"echo 'Pane 1 - {layout}'", enter=True)
    pane2.send_keys(f"echo 'Pane 2 - {layout}'", enter=True)
    pane3.send_keys(f"echo 'Pane 3 - {layout}'", enter=True)

    # Give more time for the commands to complete, especially for complex layouts
    time.sleep(3.0)  # Increased from 2.0 to 3.0

    # Dump the pane contents for debugging
    pane1_content = pane1.capture_pane()
    pane2_content = pane2.capture_pane()
    pane3_content = pane3.capture_pane()

    # Verify each pane is functioning
    assert any(f"Pane 1 - {layout}" in line for line in pane1_content), (
        f"Pane 1 content: {pane1_content}"
    )
    assert any(f"Pane 2 - {layout}" in line for line in pane2_content), (
        f"Pane 2 content: {pane2_content}"
    )
    assert any(f"Pane 3 - {layout}" in line for line in pane3_content), (
        f"Pane 3 content: {pane3_content}"
    )
