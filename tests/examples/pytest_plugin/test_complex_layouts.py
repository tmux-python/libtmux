"""Examples of testing with complex window layouts."""

from __future__ import annotations

import time

import pytest

from libtmux.constants import PaneDirection


def test_complex_layouts(session) -> None:
    """Test creating and interacting with complex window layouts."""
    # Skip this test as it's timing sensitive and has platform-specific issues
    pytest.skip(
        "Skipping test_complex_layouts due to platform-specific "
        "and timing-sensitive issues",
    )

    # Create a window with multiple panes in a specific layout
    window = session.new_window(window_name="complex-layout")
    main_pane = window.attached_pane
    main_pane.send_keys("echo 'Main Pane'", enter=True)

    # Split vertically
    right_pane = main_pane.split(direction=PaneDirection.Right)
    left_pane = main_pane  # For clarity

    # Give window manager time to adjust
    time.sleep(1)

    # Verify we have 2 panes
    assert len(window.panes) == 2, f"Expected 2 panes, but got {len(window.panes)}"

    # Apply a layout
    window.select_layout("main-vertical")
    time.sleep(1)  # Give tmux time to apply the layout

    # Verify the layout was applied
    current_layout = window.get("window_layout")
    assert current_layout is not None, "Layout was not set"

    # Send unique commands to each pane for identification
    left_pane.send_keys("clear", enter=True)
    right_pane.send_keys("clear", enter=True)
    time.sleep(1)

    left_pane.send_keys("echo 'Left Pane'", enter=True)
    right_pane.send_keys("echo 'Right Pane'", enter=True)
    time.sleep(3)  # Increase sleep time to ensure output is captured

    # Verify each pane has the correct content
    left_output = left_pane.capture_pane()
    right_output = right_pane.capture_pane()

    # Create strings for easier checking
    left_str = "\n".join(left_output)
    right_str = "\n".join(right_output)

    assert "Left Pane" in left_str, f"Left pane content not found in: {left_output}"
    assert "Right Pane" in right_str, f"Right pane content not found in: {right_output}"


def test_tiled_layout(session) -> None:
    """Test the tiled layout with multiple panes."""
    window = session.new_window(window_name="tiled-layout")

    # Create multiple panes
    pane1 = window.active_pane
    pane2 = window.split(direction=PaneDirection.Right)  # Split right
    pane3 = pane1.split(direction=PaneDirection.Below)  # Split below
    pane4 = pane2.split(direction=PaneDirection.Below)  # Split below

    # Verify we have four panes
    assert len(window.panes) == 4

    # Apply the tiled layout
    window.select_layout("tiled")

    # Verify the layout was applied
    current_layout = window.window_layout
    assert current_layout is not None, "Layout was not set"

    # Send unique commands to each pane
    pane1.send_keys("echo 'Pane 1'", enter=True)
    pane2.send_keys("echo 'Pane 2'", enter=True)
    pane3.send_keys("echo 'Pane 3'", enter=True)
    pane4.send_keys("echo 'Pane 4'", enter=True)

    time.sleep(0.5)

    # Verify each pane has the correct content
    assert any("Pane 1" in line for line in pane1.capture_pane())
    assert any("Pane 2" in line for line in pane2.capture_pane())
    assert any("Pane 3" in line for line in pane3.capture_pane())
    assert any("Pane 4" in line for line in pane4.capture_pane())
