"""Tests for libtmux logging standards compliance."""

from __future__ import annotations

import logging
import types
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


def test_server_kill_info_logging(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that server.kill() emits a lifecycle INFO record."""
    from libtmux.server import Server
    from libtmux.test.random import namer

    with Server(socket_name=f"libtmux_log_{next(namer)}") as temp_server:
        temp_server.new_session(session_name=f"log_session_{next(namer)}")
        caplog.clear()

        with caplog.at_level(logging.INFO, logger="libtmux.server"):
            temp_server.kill()

    records = [
        r
        for r in caplog.records
        if getattr(r, "tmux_subcommand", None) == "kill-server"
        and r.levelno == logging.INFO
    ]
    assert len(records) >= 1, "expected INFO record for server kill"

    rec = t.cast(t.Any, records[0])
    assert rec.getMessage() == "server killed"
    assert isinstance(rec.tmux_subcommand, str)


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


def test_window_kill_all_except_logging(
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that window.kill(all_except=True) identifies the surviving window."""
    from libtmux.test.random import namer

    survivor = session.new_window(window_name=f"log_survivor_{next(namer)}")
    other_windows = [
        session.new_window(window_name=f"log_other_{next(namer)}"),
        session.new_window(window_name=f"log_other_{next(namer)}"),
    ]

    with caplog.at_level(logging.INFO, logger="libtmux.window"):
        survivor.kill(all_except=True)

    records = [
        r
        for r in caplog.records
        if getattr(r, "tmux_subcommand", None) == "kill-window"
        and r.levelno == logging.INFO
    ]
    assert len(records) >= 1, "expected INFO record for all-except window kill"

    rec = t.cast(t.Any, records[0])
    assert rec.getMessage() == "other windows killed"
    assert rec.tmux_window == survivor.window_name
    assert rec.tmux_target == survivor.window_id
    remaining_window_ids = {window.window_id for window in session.windows}
    assert survivor.window_id in remaining_window_ids
    assert all(window.window_id not in remaining_window_ids for window in other_windows)


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


def test_pane_kill_all_except_logging(
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that pane.kill(all_except=True) identifies the surviving pane."""
    window = session.active_window
    assert window is not None
    window.resize(height=100, width=100)
    survivor = window.split()
    other_panes = [window.split(), window.split()]

    with caplog.at_level(logging.INFO, logger="libtmux.pane"):
        survivor.kill(all_except=True)

    records = [
        r
        for r in caplog.records
        if getattr(r, "tmux_subcommand", None) == "kill-pane"
        and r.levelno == logging.INFO
    ]
    assert len(records) >= 1, "expected INFO record for all-except pane kill"

    rec = t.cast(t.Any, records[0])
    assert rec.getMessage() == "other panes killed"
    assert rec.tmux_pane == survivor.pane_id
    assert rec.tmux_target == survivor.pane_id
    remaining_pane_ids = {p.pane_id for p in window.panes}
    assert survivor.pane_id in remaining_pane_ids
    assert all(p.pane_id not in remaining_pane_ids for p in other_panes)


def test_session_kill_all_except_logging(
    server: Server,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that session.kill(all_except=True) identifies the surviving session."""
    from libtmux.test.random import namer

    survivor = server.new_session(session_name=f"log_survivor_{next(namer)}")
    other_sessions = [
        server.new_session(session_name=f"log_other_{next(namer)}"),
        server.new_session(session_name=f"log_other_{next(namer)}"),
    ]

    with caplog.at_level(logging.INFO, logger="libtmux.session"):
        survivor.kill(all_except=True)

    records = [
        r
        for r in caplog.records
        if getattr(r, "tmux_subcommand", None) == "kill-session"
        and r.levelno == logging.INFO
    ]
    assert len(records) >= 1, "expected INFO record for all-except session kill"

    rec = t.cast(t.Any, records[0])
    assert rec.getMessage() == "other sessions killed"
    assert rec.tmux_session == survivor.session_name
    assert rec.tmux_target == survivor.session_id
    remaining_session_ids = {session.session_id for session in server.sessions}
    assert survivor.session_id in remaining_session_ids
    assert all(
        session.session_id not in remaining_session_ids for session in other_sessions
    )


def test_server_new_session_surfaces_kill_session_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test kill-session stderr propagation using monkeypatch for the failure path.

    A real tmux fixture is not used here because this path requires forcing a
    kill-session command failure before session creation begins.
    """
    from libtmux import exc
    from libtmux.server import Server
    from libtmux.test.random import namer

    server = Server(socket_name=f"libtmux_log_{next(namer)}")
    monkeypatch.setattr(server, "has_session", lambda session_name: True)
    monkeypatch.setattr(
        server,
        "cmd",
        lambda *args, **kwargs: types.SimpleNamespace(stderr=["kill failed"]),
    )

    with pytest.raises(exc.LibTmuxException, match="kill failed"):
        server.new_session(session_name="existing_session", kill_session=True)


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
    assert rec.exc_info is None
