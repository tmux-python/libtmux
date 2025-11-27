"""Example of waiting for shell prompt readiness."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from libtmux._internal.waiter import ContentMatchType, wait_until_pane_ready

if TYPE_CHECKING:
    from libtmux.session import Session


@pytest.mark.example
def test_wait_until_ready(session: Session) -> None:
    """Demonstrate waiting for shell readiness using a marker command.

    This test shows how to reliably detect when a shell is ready by sending
    a known command and waiting for its output, rather than trying to detect
    environment-specific shell prompts.
    """
    window = session.new_window(window_name="test_shell_ready")
    pane = window.active_pane
    assert pane is not None

    # Use a unique marker to prove shell is ready and responsive.
    # This is more reliable than trying to detect shell prompts (which vary)
    marker = "SHELL_READY_MARKER_12345"
    pane.send_keys(f"echo '{marker}'")

    # Wait for the marker - proves shell executed the command
    result = wait_until_pane_ready(
        pane,
        shell_prompt=marker,
        match_type=ContentMatchType.CONTAINS,
        timeout=10,
    )

    assert result.success, f"Shell did not become ready: {result.error}"

    window.kill()
