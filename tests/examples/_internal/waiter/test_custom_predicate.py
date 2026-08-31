"""Example of using a custom predicate function for matching."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from libtmux._internal.waiter import ContentMatchType, wait_for_pane_content

if TYPE_CHECKING:
    from libtmux.session import Session


@pytest.mark.example
def test_custom_predicate(session: Session) -> None:
    """Demonstrate using a custom predicate function for matching."""
    window = session.new_window(window_name="test_custom_predicate")
    pane = window.active_pane
    assert pane is not None

    # Send multiple lines of output
    pane.send_keys("echo 'line 1'")
    pane.send_keys("echo 'line 2'")
    pane.send_keys("echo 'line 3'")

    # Define a custom predicate function
    def check_content(lines):
        return len(lines) >= 3 and "error" not in "".join(lines).lower()

    # Use the custom predicate
    result = wait_for_pane_content(
        pane,
        check_content,
        match_type=ContentMatchType.PREDICATE,
    )
    assert result.success

    # Cleanup
    window.kill()
