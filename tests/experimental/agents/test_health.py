"""Tests for process-aliveness."""

from __future__ import annotations

import os

from libtmux.experimental.agents.health import is_alive


def test_self_is_alive() -> None:
    """Process can probe itself as alive."""
    assert is_alive(os.getpid()) is True


def test_absent_pid_is_dead() -> None:
    """Absent process is declared dead.

    PID 0x7FFFFFFF is almost certainly not a live process.
    """
    assert is_alive(2_147_483_646) is False


def test_pidless_remote_never_declared_dead() -> None:
    """PID-less remote agents never declared dead by this check."""
    assert is_alive(None) is True
