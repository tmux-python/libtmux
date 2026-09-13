"""Example of method chaining with the fluent API in libtmux waiters."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from libtmux._internal.waiter import expect

if TYPE_CHECKING:
    from libtmux.session import Session


@pytest.mark.example
def test_fluent_chaining(session: Session) -> None:
    """Demonstrate method chaining with the fluent API."""
    window = session.new_window(window_name="test_fluent_chaining")
    pane = window.active_pane
    assert pane is not None

    # Send a command
    pane.send_keys("echo 'completed successfully'")

    # With method chaining
    result = (
        expect(pane)
        .with_timeout(5.0)
        .with_interval(0.1)
        .without_raising()
        .wait_for_text("completed successfully")
    )
    assert result.success

    # Cleanup
    window.kill()
