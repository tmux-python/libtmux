"""Example of using different pattern types and match types."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from libtmux._internal.waiter import ContentMatchType, wait_for_any_content

if TYPE_CHECKING:
    from libtmux.session import Session


@pytest.mark.example
def test_mixed_pattern_types(session: Session) -> None:
    """Demonstrate using different pattern types and match types."""
    window = session.new_window(window_name="test_mixed_patterns")
    pane = window.active_pane
    assert pane is not None

    # Send commands that will match different patterns
    pane.send_keys("echo 'exact match'")
    pane.send_keys("echo '10 items found'")

    # Create a predicate function
    def has_enough_lines(lines):
        return len(lines) >= 2

    # Wait for any of these patterns with different match types
    result = wait_for_any_content(
        pane,
        [
            "exact match",  # String for exact match
            re.compile(r"\d+ items found"),  # Regex pattern
            has_enough_lines,  # Predicate function
        ],
        [ContentMatchType.EXACT, ContentMatchType.REGEX, ContentMatchType.PREDICATE],
    )
    assert result.success

    # Cleanup
    window.kill()
