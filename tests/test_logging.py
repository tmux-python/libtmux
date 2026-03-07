"""Tests for libtmux logging standards compliance."""

from __future__ import annotations

import logging
import typing as t

import pytest

if t.TYPE_CHECKING:
    from libtmux.server import Server


def test_tmux_cmd_debug_logging_schema(
    server: Server,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that tmux_cmd produces structured log records per AGENTS.md."""
    with caplog.at_level(logging.DEBUG, logger="libtmux.common"):
        server.cmd("list-sessions")
    records = [r for r in caplog.records if hasattr(r, "tmux_cmd")]
    assert len(records) >= 1
    record = records[0]
    assert isinstance(getattr(record, "tmux_cmd"), str)
    assert isinstance(getattr(record, "tmux_exit_code"), int)
