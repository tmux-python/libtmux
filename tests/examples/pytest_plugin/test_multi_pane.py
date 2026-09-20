"""Example of using multiple panes in tmux tests."""

from __future__ import annotations

import time

from libtmux.constants import PaneDirection


def test_multi_pane_interaction(server, session) -> None:
    """Test interaction between multiple panes."""
    # Create a window for testing multi-pane interactions
    window = session.new_window(window_name="multi-pane-test")

    # Initialize the main pane
    main_pane = window.active_pane

    # Create a second pane for output
    output_pane = window.split(direction=PaneDirection.Right)

    # Create a third pane for monitoring
    monitor_pane = main_pane.split(direction=PaneDirection.Below)

    # Wait for panes to be ready
    time.sleep(0.5)

    # Verify we have three panes
    assert len(window.panes) == 3

    # Send a command to the main pane
    main_pane.send_keys("echo 'Hello from main pane'", enter=True)
    time.sleep(0.5)

    # Send a command to the output pane
    output_pane.send_keys("echo 'Hello from output pane'", enter=True)
    time.sleep(0.5)

    # Send a command to the monitor pane
    monitor_pane.send_keys("echo 'Hello from monitor pane'", enter=True)
    time.sleep(0.5)

    # Refresh the window to get updated pane information
    window.refresh()

    # Verify all panes are still accessible
    assert main_pane.id is not None
    assert output_pane.id is not None
    assert monitor_pane.id is not None


def test_pane_layout(session) -> None:
    """Test complex pane layouts."""
    # Create a window for testing layouts
    window = session.new_window(window_name="layout-test")

    # Get the initial pane
    top_pane = window.active_pane

    # Create a layout with multiple panes
    right_pane = window.split(direction=PaneDirection.Right)
    bottom_left = top_pane.split(direction=PaneDirection.Below)
    bottom_right = right_pane.split(direction=PaneDirection.Below)

    # Check the number of panes
    assert len(window.panes) == 4

    # Apply the tiled layout
    window.select_layout("tiled")

    # Verify all panes are accessible
    assert top_pane.id is not None
    assert right_pane.id is not None
    assert bottom_left.id is not None
    assert bottom_right.id is not None
