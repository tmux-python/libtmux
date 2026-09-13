"""Example of waiting for shell prompt readiness."""

from __future__ import annotations

import contextlib
import re
from typing import TYPE_CHECKING

import pytest

from libtmux._internal.waiter import ContentMatchType, wait_until_pane_ready

if TYPE_CHECKING:
    from libtmux.session import Session


@pytest.mark.example
@pytest.mark.skip(reason="Test is unreliable in CI environment due to timing issues")
def test_wait_until_ready(session: Session) -> None:
    """Demonstrate waiting for shell prompt."""
    window = session.new_window(window_name="test_shell_ready")
    pane = window.active_pane
    assert pane is not None

    # Force shell prompt by sending a few commands and waiting
    pane.send_keys("echo 'test command'")
    pane.send_keys("ls")

    # For test purposes, look for any common shell prompt characters
    # The wait_until_pane_ready function works either with:
    # 1. A string to find (will use CONTAINS match_type)
    # 2. A predicate function taking lines and returning bool
    # (will use PREDICATE match_type)

    # Using a regex to match common shell prompt characters: $, %, >, #

    # Try with a simple string first
    result = wait_until_pane_ready(
        pane,
        shell_prompt="$",
        timeout=10,  # Increased timeout
    )

    if not result.success:
        # Fall back to regex pattern if the specific character wasn't found
        result = wait_until_pane_ready(
            pane,
            shell_prompt=re.compile(r"[$%>#]"),  # Using standard prompt characters
            match_type=ContentMatchType.REGEX,
            timeout=10,  # Increased timeout
        )

    assert result.success

    # Only kill the window if the test is still running
    with contextlib.suppress(Exception):
        window.kill()
