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
    records = [r for r in caplog.records if hasattr(r, "tmux_exit_code")]
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
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test kill-session stderr propagation, and the ERROR record it emits.

    ``has_session`` is monkeypatched so ``new_session`` attempts to kill a
    session that does not exist; tmux then fails the ``kill-session`` for real,
    which is the condition under test.
    """
    from libtmux import exc

    monkeypatch.setattr(server, "has_session", lambda session_name: True)

    with (
        caplog.at_level(logging.ERROR, logger="libtmux.common"),
        pytest.raises(exc.LibTmuxException, match="kill-session"),
    ):
        server.new_session(session_name="no_such_session", kill_session=True)

    records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(records) >= 1, "expected ERROR record for the failed kill-session"

    rec = t.cast(t.Any, records[0])
    assert rec.getMessage() == "tmux command failed"
    assert rec.tmux_subcommand == "kill-session"
    assert isinstance(rec.tmux_exit_code, int)
    assert rec.tmux_exit_code != 0
    assert rec.tmux_stderr_len >= 1


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


@pytest.mark.parametrize(
    ("argv", "subcommand", "socket"),
    [
        (["tmux", "-Lsock", "new-session"], "new-session", "sock"),
        (["tmux", "-L", "sock", "new-session"], "new-session", "sock"),
        (["tmux", "-S", "/tmp/s", "kill-server"], "kill-server", "/tmp/s"),
        (["tmux", "-f", "/etc/tmux.conf", "kill-server"], "kill-server", None),
        (["tmux", "-2", "-q", "list-panes"], "list-panes", None),
        (["tmux", "-c", "echo hi", "run-shell"], "run-shell", None),
        (["tmux", "-T", "256", "list-keys"], "list-keys", None),
        (["tmux", "-V"], None, None),
    ],
    ids=[
        "joined-socket",
        "separated-socket",
        "socket-path",
        "separated-config",
        "bundled-booleans",
        "separated-shell-command",
        "separated-features",
        "no-subcommand",
    ],
)
def test_describe_command_reads_tmux_global_flags(
    argv: list[str],
    subcommand: str | None,
    socket: str | None,
) -> None:
    """Global flags that take a value must not be read as the subcommand.

    Mirrors tmux's own ``getopt`` string in ``tmux.c`` (``2c:CDdf:hlL:NqS:T:uUvV``).
    libtmux always joins its own flags, so only a caller building a command line
    by hand reaches the separated forms.
    """
    from libtmux._internal.log_context import describe_command

    context = describe_command(argv)
    assert context.subcommand == subcommand
    assert context.socket == socket


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["tmux", "new-session", "-eK=v"], "tmux new-session -eK=REDACTED"),
        (["tmux", "new-session", "-e", "K=v"], "tmux new-session -e K=REDACTED"),
        (["tmux", "split-window", "-eK=a=b"], "tmux split-window -eK=REDACTED"),
        (["tmux", "set-environment", "K", "v"], "tmux set-environment K REDACTED"),
        (["tmux", "set-environment", "-u", "K"], "tmux set-environment -u K"),
        (["tmux", "select-pane", "-e", "-t%1"], "tmux select-pane -e -t%1"),
        (["tmux", "copy-mode", "-e"], "tmux copy-mode -e"),
    ],
    ids=[
        "joined-env-pair",
        "separated-env-pair",
        "value-containing-equals",
        "set-environment-value",
        "set-environment-unset-keeps-name",
        "select-pane-boolean-e",
        "copy-mode-boolean-e",
    ],
)
def test_describe_command_redacts_only_environment_values(
    argv: list[str],
    expected: str,
) -> None:
    """``-e`` is an env pair on some subcommands and a boolean on others."""
    from libtmux._internal.log_context import describe_command

    assert describe_command(argv).command == expected


def test_command_records_carry_socket_identity(
    server: Server,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Records name which tmux server they came from."""
    with caplog.at_level(logging.DEBUG, logger="libtmux.common"):
        server.cmd("list-sessions")

    records = [r for r in caplog.records if hasattr(r, "tmux_socket")]
    assert len(records) >= 1, "expected records tagged with the socket"

    rec = t.cast(t.Any, records[0])
    assert rec.tmux_socket == server.socket_name
    assert rec.tmux_subcommand == "list-sessions"


def test_server_kill_session_info_logging(
    server: Server,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Server.kill_session() logs the same lifecycle event Session.kill() does."""
    from libtmux.test.random import namer

    name = f"log_kill_{next(namer)}"
    server.new_session(session_name=name)

    with caplog.at_level(logging.INFO, logger="libtmux.server"):
        server.kill_session(name)

    records = [
        r
        for r in caplog.records
        if getattr(r, "tmux_subcommand", None) == "kill-session"
        and r.levelno == logging.INFO
    ]
    assert len(records) >= 1, "expected INFO record for Server.kill_session()"

    rec = t.cast(t.Any, records[0])
    assert rec.getMessage() == "session killed"
    assert rec.tmux_target == name


def test_session_fixture_setup_logs_no_errors(
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The bundled fixtures must not leave ERROR records in a test's report.

    pytest replays captured records into the report of every failing test, so a
    fixture that provokes a tmux failure reads as the cause of that failure.
    """
    assert session.session_name is not None

    errors = [r for r in caplog.get_records("setup") if r.levelno >= logging.ERROR]
    assert errors == [], f"fixture setup logged: {[r.getMessage() for r in errors]}"
