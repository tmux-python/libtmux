"""Example of using the fluent API in libtmux waiters."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from libtmux._internal.waiter import expect

if TYPE_CHECKING:
    from libtmux.session import Session


@pytest.mark.example
def test_fluent_basic(session: Session) -> None:
    """Demonstrate basic usage of the fluent API."""
    window = session.new_window(window_name="test_fluent_basic")
    pane = window.active_pane
    assert pane is not None

    # Send a command
    pane.send_keys("echo 'hello world'")

    # Basic usage of the fluent API
    result = expect(pane).wait_for_text("hello world")
    assert result.success

    # Cleanup
    window.kill()
