"""Tests for libtmux logging standards compliance."""

from __future__ import annotations

import logging
import typing as t

import pytest

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session


def test_tmux_cmd_debug_logging_schema(
    server: Server,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that tmux_cmd produces structured log records per AGENTS.md."""
    with caplog.at_level(logging.DEBUG, logger="libtmux.common"):
        server.cmd("list-sessions")
    records = [r for r in caplog.records if hasattr(r, "tmux_cmd")]
    assert len(records) >= 1
    record = t.cast(t.Any, records[0])
    assert isinstance(record.tmux_cmd, str)
    assert isinstance(record.tmux_exit_code, int)


def test_lifecycle_info_logging_schema(
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that lifecycle operations produce INFO records with str-typed extra."""
    with caplog.at_level(logging.INFO, logger="libtmux.session"):
        window = session.new_window(window_name="log_test")

    records = [
        r
        for r in caplog.records
        if hasattr(r, "tmux_subcommand") and r.levelno == logging.INFO
    ]
    assert len(records) >= 1, "expected at least one INFO lifecycle record"

    for record in records:
        rec = t.cast(t.Any, record)
        for key in ("tmux_subcommand", "tmux_session", "tmux_window", "tmux_target"):
            val = getattr(rec, key, None)
            if val is not None:
                assert isinstance(val, str), (
                    f"extra key {key!r} should be str, got {type(val).__name__}"
                )

    window.kill()


def test_server_new_session_info_logging(
    server: Server,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that server.new_session() produces INFO record with str-typed extra."""
    with caplog.at_level(logging.INFO, logger="libtmux.server"):
        new_session = server.new_session(session_name="log_test_session")

    records = [
        r
        for r in caplog.records
        if hasattr(r, "tmux_subcommand")
        and r.levelno == logging.INFO
        and getattr(r, "tmux_subcommand", None) == "new-session"
    ]
    assert len(records) >= 1, "expected INFO record for session creation"

    rec = t.cast(t.Any, records[0])
    assert isinstance(rec.tmux_subcommand, str)
    assert isinstance(rec.tmux_session, str)

    new_session.kill()


def test_window_rename_info_logging(
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that window.rename_window() produces INFO record with str-typed extra."""
    window = session.active_window
    assert window is not None
    with caplog.at_level(logging.INFO, logger="libtmux.window"):
        window.rename_window("log_renamed")

    records = [
        r
        for r in caplog.records
        if hasattr(r, "tmux_subcommand")
        and r.levelno == logging.INFO
        and getattr(r, "tmux_subcommand", None) == "rename-window"
    ]
    assert len(records) >= 1, "expected INFO record for window rename"

    rec = t.cast(t.Any, records[0])
    assert isinstance(rec.tmux_subcommand, str)
    for key in ("tmux_window", "tmux_target"):
        val = getattr(rec, key, None)
        if val is not None:
            assert isinstance(val, str), (
                f"extra key {key!r} should be str, got {type(val).__name__}"
            )


def test_pane_split_info_logging(
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that pane.split() produces INFO record with str-typed extra."""
    window = session.active_window
    assert window is not None
    pane = window.active_pane
    assert pane is not None
    with caplog.at_level(logging.INFO, logger="libtmux.pane"):
        new_pane = pane.split()

    records = [
        r
        for r in caplog.records
        if hasattr(r, "tmux_subcommand")
        and r.levelno == logging.INFO
        and getattr(r, "tmux_subcommand", None) == "split-window"
    ]
    assert len(records) >= 1, "expected INFO record for pane split"

    rec = t.cast(t.Any, records[0])
    assert isinstance(rec.tmux_subcommand, str)
    assert isinstance(rec.tmux_pane, str)
    for key in ("tmux_session", "tmux_window"):
        val = getattr(rec, key, None)
        if val is not None:
            assert isinstance(val, str), (
                f"extra key {key!r} should be str, got {type(val).__name__}"
            )

    new_pane.kill()


def test_options_warning_logging_schema(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that options parse warnings produce records with tmux_option_key."""
    from libtmux._internal.sparse_array import SparseArray
    from libtmux.options import explode_complex

    # A terminal-features value without ":" triggers a split failure and WARNING
    bad_features: SparseArray[str | int | bool | None] = SparseArray()
    bad_features[0] = 42  # int, not str — causes .split() to fail

    with caplog.at_level(logging.WARNING, logger="libtmux.options"):
        explode_complex({"terminal-features": bad_features})  # type: ignore[dict-item]

    records = [
        r
        for r in caplog.records
        if hasattr(r, "tmux_option_key") and r.levelno == logging.WARNING
    ]
    assert len(records) >= 1, "expected WARNING record for option parse failure"

    rec = t.cast(t.Any, records[0])
    assert isinstance(rec.tmux_option_key, str)
