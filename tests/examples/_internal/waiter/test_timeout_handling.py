"""Example of timeout handling with libtmux waiters."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from libtmux._internal.waiter import wait_for_pane_content

if TYPE_CHECKING:
    from libtmux.session import Session


@pytest.mark.example
def test_timeout_handling(session: Session) -> None:
    """Demonstrate handling timeouts gracefully without exceptions."""
    window = session.new_window(window_name="test_timeout")
    pane = window.active_pane
    assert pane is not None

    # Clear the pane
    pane.send_keys("clear")

    # Handle timeouts gracefully without exceptions
    # Looking for content that won't appear (with a short timeout)
    result = wait_for_pane_content(
        pane,
        "this text will not appear",
        timeout=0.5,
        raises=False,
    )

    # Should not raise an exception
    assert not result.success
    assert result.error is not None
    assert "Timed out" in result.error

    # Cleanup
    window.kill()
