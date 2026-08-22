"""Tests for libtmux logging standards compliance."""

from __future__ import annotations

import concurrent.futures
import logging
import pathlib
import typing as t

import pytest

from libtmux.test.retry import retry_until

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
    assert isinstance(record.tmux_stdout_len, int)
    assert isinstance(record.tmux_stderr_len, int)
    assert not hasattr(record, "tmux_stdout")
    assert not hasattr(record, "tmux_stderr")


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
        assert rec.tmux_socket == session.server.socket_name
        for key in (
            "tmux_subcommand",
            "tmux_socket",
            "tmux_session",
            "tmux_window",
            "tmux_target",
        ):
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


def test_server_new_session_propagates_without_logging(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A propagated tmux failure remains exception data, not a log record."""
    from libtmux import exc

    monkeypatch.setattr(server, "has_session", lambda session_name: True)

    with (
        caplog.at_level(logging.ERROR, logger="libtmux.common"),
        pytest.raises(exc.LibTmuxException, match="kill-session"),
    ):
        server.new_session(session_name="no_such_session", kill_session=True)

    assert [r for r in caplog.records if r.levelno == logging.ERROR] == []


def test_environment_failure_propagates_without_logging(
    server: Server,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A translated environment failure remains exception data only."""
    dead = server.new_session(session_name="logging_dead_environment")
    dead.kill()

    with (
        caplog.at_level(logging.ERROR, logger="libtmux.common"),
        pytest.raises(ValueError),
    ):
        dead.set_environment("KEY", "value")

    assert [r for r in caplog.records if r.levelno == logging.ERROR] == []


@pytest.mark.parametrize("configured", [True, False], ids=["configured", "default"])
def test_missing_tmux_binary_propagates_without_logging(
    configured: bool,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A missing executable remains exception data, not a log record."""
    from libtmux import exc
    from libtmux.common import tmux_cmd

    tmux_bin = str(tmp_path / "missing-tmux") if configured else None
    if not configured:
        monkeypatch.setattr("libtmux.common.shutil.which", lambda _: None)
    with (
        caplog.at_level(logging.ERROR, logger="libtmux.common"),
        pytest.raises(exc.TmuxCommandNotFound),
    ):
        tmux_cmd("list-sessions", tmux_bin=tmux_bin)

    assert [r for r in caplog.records if r.levelno == logging.ERROR] == []


@pytest.mark.parametrize(
    "binary_case",
    ["configured-missing", "default-missing", "invalid-format"],
)
def test_is_alive_unusable_binary_stays_quiet(
    binary_case: str,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A health check converts an unusable executable to a quiet ``False``."""
    from libtmux.server import Server

    tmux_bin: str | None = str(tmp_path / "missing-tmux")
    if binary_case == "default-missing":
        tmux_bin = None
        monkeypatch.setenv("PATH", "")
    elif binary_case == "invalid-format":
        invalid_tmux = tmp_path / "invalid-tmux"
        invalid_tmux.write_text("not an executable format\n")
        invalid_tmux.chmod(0o755)
        tmux_bin = str(invalid_tmux)
    server = Server(tmux_bin=tmux_bin)

    with caplog.at_level(logging.ERROR, logger="libtmux.common"):
        assert not server.is_alive()

    assert [
        record for record in caplog.records if record.levelno == logging.ERROR
    ] == []


def test_options_warning_logging_schema(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that options parse warnings produce records with tmux_option_key."""
    from libtmux._internal.sparse_array import SparseArray
    from libtmux.options import explode_complex

    # ints rather than "term:feature" strings, so every .split() fails
    bad_features: SparseArray[str | int | bool | None] = SparseArray()
    for index in range(25):
        bad_features[index] = index

    with caplog.at_level(logging.WARNING, logger="libtmux.options"):
        explode_complex({"terminal-features": bad_features})  # type: ignore[dict-item]

    records = [
        r
        for r in caplog.records
        if hasattr(r, "tmux_option_key") and r.levelno == logging.WARNING
    ]
    assert len(records) == 1, (
        f"one option should warn once, not once per entry; got {len(records)}"
    )

    rec = t.cast(t.Any, records[0])
    assert isinstance(rec.tmux_option_key, str)
    assert rec.tmux_option_skipped == 25
    assert rec.exc_info is None


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (
            ["tmux", "-Lsock", "new-session", "-eKEY=secret"],
            {
                "tmux_cmd": "tmux -L sock new-session <1 arguments omitted>",
                "tmux_subcommand": "new-session",
                "tmux_socket": "sock",
            },
        ),
        (
            ["tmux", "-S", "/tmp/s", "set-buffer", "secret"],
            {
                "tmux_cmd": "tmux -S /tmp/s set-buffer <1 arguments omitted>",
                "tmux_subcommand": "set-buffer",
                "tmux_socket": "/tmp/s",
            },
        ),
        (
            ["tmux", "-f", "secret-conf", "run-shell", "secret"],
            {
                "tmux_cmd": "tmux run-shell <1 arguments omitted>",
                "tmux_subcommand": "run-shell",
            },
        ),
        (
            ["tmux", "-2L", "sock", "list-panes"],
            {
                "tmux_cmd": "tmux -L sock list-panes",
                "tmux_subcommand": "list-panes",
                "tmux_socket": "sock",
            },
        ),
        (
            ["tmux", "-L", "safe\nforged", "future-command", "secret"],
            {
                "tmux_cmd": (
                    "tmux -L 'safe\\nforged' future-command <1 arguments omitted>"
                ),
                "tmux_subcommand": "future-command",
                "tmux_socket": "'safe\\nforged'",
            },
        ),
        (["tmux", "-V"], {"tmux_cmd": "tmux"}),
    ],
)
def test_command_extra_separates_operation_from_parameters(
    argv: list[str],
    expected: dict[str, str],
) -> None:
    """Operation records identify tmux without carrying parameter data."""
    from libtmux._internal.log_context import command_extra

    assert command_extra(argv) == expected


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


def test_command_content_cannot_forge_a_log_line(
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A newline a caller sends must not end the record and start a new one.

    ``send_keys`` carries whatever the caller types, so a multi-line payload
    would otherwise split one record across several lines of a line-oriented
    log, where the remainder reads as a record of its own.
    """
    pane = session.active_window.active_pane
    assert pane is not None

    with caplog.at_level(logging.DEBUG, logger="libtmux.common"):
        pane.send_keys("echo hi\nCRITICAL libtmux.server forged", enter=False)

    dispatched = [
        r for r in caplog.records if r.getMessage() == "tmux command dispatched"
    ]
    assert len(dispatched) >= 1

    rec = t.cast(t.Any, dispatched[-1])
    assert "\n" not in rec.tmux_cmd
    assert "CRITICAL libtmux.server forged" not in rec.tmux_cmd
    assert rec.tmux_cmd.endswith("send-keys <3 arguments omitted>")


def test_lookup_path_cannot_forge_a_log_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed caller-provided lookup stays on one diagnostic line."""
    from libtmux._internal.query_list import keygetter

    with caplog.at_level(logging.DEBUG, logger="libtmux._internal.query_list"):
        keygetter({}, "missing\nERROR libtmux forged")

    record = caplog.records[-1]
    assert "\n" not in record.getMessage()
    assert "\\nERROR libtmux forged" in record.getMessage()


def test_pane_content_is_not_written_to_records(
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Terminal content reaches the caller as a return value, not as a record.

    A pane holds whatever was typed into it, so its contents are the tmux
    equivalent of an HTTP response body: the record reports how much came back.
    """
    pane = session.active_window.active_pane
    assert pane is not None
    marker = "hunter2-typed-into-the-pane"
    pane.send_keys(f"# {marker}", enter=True)
    retry_until(lambda: any(marker in line for line in pane.capture_pane()), 2)

    with caplog.at_level(logging.DEBUG, logger="libtmux.common"):
        captured = pane.capture_pane()

    assert any(marker in line for line in captured), "caller still gets the content"

    records = [r for r in caplog.records if r.getMessage() == "tmux command completed"]
    assert records, "expected a completion record"
    for record in records:
        rec = t.cast(t.Any, record)
        assert not hasattr(rec, "tmux_stdout")
        assert not hasattr(rec, "tmux_stderr")
        if rec.tmux_subcommand == "capture-pane":
            assert rec.tmux_stdout_len > 0, "the count still reports what came back"


def test_parse_failure_propagates_without_logging(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A parser failure remains exception data, not a second error channel."""
    from libtmux.formats import FORMAT_SEPARATOR
    from libtmux.neo import parse_output

    row = FORMAT_SEPARATOR.join(["one", "two", "three"]) + FORMAT_SEPARATOR

    with (
        caplog.at_level(logging.ERROR, logger="libtmux.neo"),
        pytest.raises(ValueError, match="zip"),
    ):
        parse_output(row, "list-panes", "3.7")

    assert [r for r in caplog.records if r.levelno == logging.ERROR] == []


def test_concurrent_records_keep_operation_context(
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Concurrent commands keep their fields isolated.

    Handler locks make :mod:`logging` itself thread-safe, so the only way
    libtmux could introduce a race is by handing the same list or dict to more
    than one record.
    """
    server = session.server
    markers = [f"concurrent-{index}" for index in range(8)]
    with (
        caplog.at_level(logging.DEBUG, logger="libtmux.common"),
        concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor,
    ):
        futures = [
            executor.submit(server.cmd, "display-message", "-p", marker)
            for marker in markers
        ]
        results = [future.result() for future in futures]

    assert [result.stdout for result in results] == [[marker] for marker in markers]
    completed = [
        record
        for record in caplog.records
        if record.getMessage() == "tmux command completed"
        and getattr(record, "tmux_subcommand", None) == "display-message"
    ]
    assert len(completed) == len(markers)
    assert all(
        t.cast(t.Any, record).tmux_socket == server.socket_name for record in completed
    )
    assert all(t.cast(t.Any, record).tmux_stdout_len == 1 for record in completed)
    assert all(not hasattr(record, "tmux_stdout") for record in completed)
