"""Example of waiting for text in a pane."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from libtmux._internal.waiter import wait_for_pane_content

if TYPE_CHECKING:
    from libtmux.session import Session


@pytest.mark.example
def test_wait_for_text(session: Session) -> None:
    """Demonstrate waiting for text in a pane."""
    # Create a window and pane for testing
    window = session.new_window(window_name="test_wait_for_text")
    pane = window.active_pane
    assert pane is not None

    # Send a command to the pane
    pane.send_keys("echo 'hello world'")

    # Wait for text to appear
    result = wait_for_pane_content(pane, "hello world")
    assert result.success

    # Cleanup
    window.kill()
