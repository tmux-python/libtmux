"""Example test demonstrating custom session parameters.

This example shows how to customize the session fixture parameters.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def session_params():
    """Override session_params to specify custom session dimensions."""
    return {"x": 800, "y": 600}


def test_custom_session_dimensions(session) -> None:
    """Test that session is created with custom dimensions."""
    assert session

    # Optional: Additional assertions about session dimensions
    # These would require accessing tmux directly to verify the dimensions
    # but we include the example for documentation completeness
