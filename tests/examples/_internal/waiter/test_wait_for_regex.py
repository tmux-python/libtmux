"""Example of waiting for text matching a regex pattern."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from libtmux._internal.waiter import ContentMatchType, wait_for_pane_content

if TYPE_CHECKING:
    from libtmux.session import Session


@pytest.mark.example
def test_wait_for_regex(session: Session) -> None:
    """Demonstrate waiting for text matching a regular expression."""
    window = session.new_window(window_name="test_regex_matching")
    pane = window.active_pane
    assert pane is not None

    # Send a command to the pane
    pane.send_keys("echo 'hello world'")

    # Wait for text matching a regular expression
    pattern = re.compile(r"hello \w+")
    result = wait_for_pane_content(pane, pattern, match_type=ContentMatchType.REGEX)
    assert result.success

    # Cleanup
    window.kill()
