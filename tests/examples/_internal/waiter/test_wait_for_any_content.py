"""Example of waiting for any of multiple conditions."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from libtmux._internal.waiter import ContentMatchType, wait_for_any_content

if TYPE_CHECKING:
    from libtmux.session import Session


@pytest.mark.example
def test_wait_for_any_content(session: Session) -> None:
    """Demonstrate waiting for any of multiple conditions."""
    window = session.new_window(window_name="test_any_content")
    pane = window.active_pane
    assert pane is not None

    # Send a command
    pane.send_keys("echo 'Success'")

    # Wait for any of these patterns
    result = wait_for_any_content(
        pane,
        ["Success", "Error:", "timeout"],
        ContentMatchType.CONTAINS,
    )
    assert result.success
    assert result.matched_content == "Success"
    assert result.matched_pattern_index == 0

    # Cleanup
    window.kill()
