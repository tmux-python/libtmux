"""Example of waiting for all conditions to be met."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from libtmux._internal.waiter import ContentMatchType, wait_for_all_content

if TYPE_CHECKING:
    from libtmux.session import Session


@pytest.mark.example
def test_wait_for_all_content(session: Session) -> None:
    """Demonstrate waiting for all conditions to be met."""
    window = session.new_window(window_name="test_all_content")
    pane = window.active_pane
    assert pane is not None

    # Send commands with both required phrases
    pane.send_keys("echo 'Database connected'")
    pane.send_keys("echo 'Server started'")

    # Wait for all conditions to be true
    result = wait_for_all_content(
        pane,
        ["Database connected", "Server started"],
        ContentMatchType.CONTAINS,
    )
    assert result.success
    # For wait_for_all_content, the matched_content will be a list of matched patterns
    assert result.matched_content is not None
    matched_content = cast("list[str]", result.matched_content)
    assert len(matched_content) == 2
    assert "Database connected" in matched_content
    assert "Server started" in matched_content

    # Cleanup
    window.kill()
