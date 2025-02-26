"""Pytest configuration for waiter examples."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import pytest

from libtmux import Server

if TYPE_CHECKING:
    from collections.abc import Generator

    from libtmux.session import Session


@pytest.fixture
def session() -> Generator[Session, None, None]:
    """Provide a tmux session for tests.

    This fixture creates a new session specifically for the waiter examples,
    and ensures it's properly cleaned up after the test.
    """
    server = Server()
    session_name = "waiter_example_tests"

    # Clean up any existing session with this name
    with contextlib.suppress(Exception):
        # Instead of using deprecated methods, use more direct approach
        server.cmd("kill-session", "-t", session_name)

    # Create a new session
    session = server.new_session(session_name=session_name)

    yield session

    # Clean up
    with contextlib.suppress(Exception):
        session.kill()
