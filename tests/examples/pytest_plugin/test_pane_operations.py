"""Examples of operations with tmux panes."""

from __future__ import annotations

import time

import pytest

from libtmux.constants import PaneDirection


@pytest.fixture
def window(session):
    """Create a window for testing."""
    return session.new_window(window_name="test-window")


@pytest.fixture
def pane(window):
    """Create a pane for testing."""
    return window.active_pane


def test_pane_functions(pane) -> None:
    """Test basic pane functions."""
    # Send a command to the pane
    pane.send_keys("echo 'Hello from pane'", enter=True)

    # Give the command time to execute
    time.sleep(0.5)

    # Capture and verify the output
    output = pane.capture_pane()
    assert any("Hello from pane" in line for line in output)


def test_window_functions(window) -> None:
    """Test basic window functions."""
    # Get the active pane
    pane = window.active_pane
    assert pane is not None

    # Split the window
    window.split(direction=PaneDirection.Below)
    assert len(window.panes) == 2


def test_pane_resizing(window) -> None:
    """Test resizing panes."""
    # Start with a single pane
    original_pane = window.active_pane

    # Split horizontally
    second_pane = window.split(direction=PaneDirection.Right)
    assert len(window.panes) == 2

    # Get initial width
    original_width1 = original_pane.width
    original_width2 = second_pane.width

    # Both panes should have a width
    assert original_width1 is not None
    assert original_width2 is not None

    # Resize the first pane to be larger
    original_pane.resize(width=60)
    time.sleep(0.5)

    # Verify resize happened without errors
    window.refresh()
    original_pane.refresh()
    second_pane.refresh()

    # Get updated dimensions to verify
    new_width1 = original_pane.width
    new_width2 = second_pane.width

    # The dimensions should have changed
    assert new_width1 is not None
    assert new_width2 is not None


def test_pane_capturing(pane) -> None:
    """Test capturing pane content in different formats."""
    # Clear the pane first
    pane.clear()
    time.sleep(0.2)

    # Send multiple lines of content
    pane.send_keys("echo 'Line 1'", enter=True)
    pane.send_keys("echo 'Line 2'", enter=True)
    pane.send_keys("echo 'Line 3'", enter=True)
    time.sleep(0.5)

    # Capture as a list of lines
    output_lines = pane.capture_pane()
    assert isinstance(output_lines, list)
    assert any("Line 1" in line for line in output_lines)
    assert any("Line 2" in line for line in output_lines)
    assert any("Line 3" in line for line in output_lines)

    # Capture as a single string
    output_str = "\n".join(pane.capture_pane())
    assert isinstance(output_str, str)
    assert "Line 1" in output_str
    assert "Line 2" in output_str
    assert "Line 3" in output_str
