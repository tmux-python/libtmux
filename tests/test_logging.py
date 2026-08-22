"""Tests for libtmux logging standards compliance."""

from __future__ import annotations

import concurrent.futures
import contextlib
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

    assert [
        record for record in caplog.records if record.levelno == logging.ERROR
    ] == []


def test_environment_failure_propagates_without_logging(
    server: Server,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Translated environment errors remain exception data."""
    dead = server.new_session(session_name="logging_dead_environment")
    dead.kill()

    with (
        caplog.at_level(logging.ERROR, logger="libtmux.common"),
        pytest.raises(ValueError),
    ):
        dead.set_environment("KEY", "value")

    assert [
        record for record in caplog.records if record.levelno == logging.ERROR
    ] == []


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

    assert [
        record for record in caplog.records if record.levelno == logging.ERROR
    ] == []


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
    ("argv", "subcommand", "socket"),
    [
        (["tmux", "-Lsock", "new-session"], "new-session", "sock"),
        (["tmux", "-L", "sock", "new-session"], "new-session", "sock"),
        (["tmux", "-S", "/tmp/s", "kill-server"], "kill-server", "/tmp/s"),
        (["tmux", "-f", "/etc/tmux.conf", "kill-server"], "kill-server", None),
        (["tmux", "-2", "-q", "list-panes"], "list-panes", None),
        (["tmux", "-2Lsock", "new-session"], "new-session", "sock"),
        (["tmux", "-2L", "sock", "new-session"], "new-session", "sock"),
        (["tmux", "-qu", "-S", "/tmp/x", "kill-server"], "kill-server", "/tmp/x"),
        (["tmux", "-c", "echo hi", "run-shell"], "run-shell", None),
        (["tmux", "-T", "256", "list-keys"], "list-keys", None),
        (
            ["tmux", "-L", "label", "-S", "/tmp/path", "list-sessions"],
            "list-sessions",
            "/tmp/path",
        ),
        (
            ["tmux", "-S/path", "-Llabel", "list-sessions"],
            "list-sessions",
            "/path",
        ),
        (["tmux", "-V"], None, None),
    ],
    ids=[
        "joined-socket",
        "separated-socket",
        "socket-path",
        "separated-config",
        "bundled-booleans",
        "boolean-bundled-with-socket",
        "boolean-bundled-socket-takes-next",
        "bundled-booleans-then-socket-path",
        "separated-shell-command",
        "separated-features",
        "path-after-label",
        "path-before-label",
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
        (
            ["tmux", "setenv", "-Ft", "work", "K", "-secret"],
            "tmux setenv -Ft work K REDACTED",
        ),
        (["tmux", "set-environment", "-u", "K"], "tmux set-environment -u K"),
        (["tmux", "select-pane", "-e", "-t%1"], "tmux select-pane -e -t%1"),
        (["tmux", "select-pane", "-eK=v"], "tmux select-pane -eK=v"),
        (["tmux", "copy-mode", "-e"], "tmux copy-mode -e"),
        (
            ["tmux", "new-session", "-c/tmp/secret=path"],
            "tmux new-session -c/tmp/secret=path",
        ),
        (
            ["tmux", "set-buffer", "-b", "named", "secret data"],
            "tmux set-buffer -b named REDACTED",
        ),
        (["tmux", "setb", "secret data"], "tmux setb REDACTED"),
        (["tmux", "set-e", "K", "secret"], "tmux set-e K REDACTED"),
        (["tmux", "set-b", "secret data"], "tmux set-b REDACTED"),
    ],
    ids=[
        "joined-env-pair",
        "separated-env-pair",
        "value-containing-equals",
        "set-environment-value",
        "setenv-dash-prefixed-value",
        "set-environment-unset-keeps-name",
        "select-pane-boolean-e",
        "select-pane-joined-boolean-e",
        "copy-mode-boolean-e",
        "other-option-attached-value",
        "set-buffer-content",
        "setb-content",
        "set-environment-prefix",
        "set-buffer-prefix",
    ],
)
def test_describe_command_redacts_only_environment_values(
    argv: list[str],
    expected: str,
) -> None:
    """``-e`` is an env pair on some subcommands and a boolean on others."""
    from libtmux._internal.log_context import describe_command

    context = describe_command(argv)
    assert context.subcommand == argv[1]
    assert context.command == expected


def test_describe_command_redacts_every_environment_spelling() -> None:
    """Every built-in and default alias that accepts ``-e`` hides its value."""
    from libtmux._internal.log_context import describe_command

    subcommands = (
        "new-session",
        "new",
        "new-window",
        "neww",
        "new-pane",
        "newp",
        "display-popup",
        "popup",
        "respawn-pane",
        "respawnp",
        "respawn-window",
        "respawnw",
        "split-window",
        "splitw",
        "split-pane",
        "splitp",
        "new-s",
        "new-w",
        "new-p",
        "display-po",
        "respawn-p",
        "respawn-w",
        "sp",
    )
    for subcommand in subcommands:
        joined = describe_command(["tmux", subcommand, "-eKEY=secret"])
        separated = describe_command(["tmux", subcommand, "-e", "KEY=secret"])
        assert joined.command == f"tmux {subcommand} -eKEY=REDACTED"
        assert separated.command == f"tmux {subcommand} -e KEY=REDACTED"


@pytest.mark.parametrize(
    ("subcommand", "boolean_flags"),
    (
        ("new-session", "-d"),
        ("new-window", "-d"),
        ("new-pane", "-df"),
        ("display-popup", "-BE"),
        ("respawn-pane", "-k"),
        ("respawn-window", "-k"),
        ("split-window", "-dP"),
    ),
)
def test_describe_command_redacts_bundled_environment_options(
    subcommand: str,
    boolean_flags: str,
) -> None:
    """Boolean flags before value-taking ``-e`` cannot expose its value."""
    from libtmux._internal.log_context import describe_command

    option = f"{boolean_flags}eKEY=secret"

    context = describe_command(["tmux", subcommand, option])

    assert context.command == f"tmux {subcommand} {boolean_flags}eKEY=REDACTED"


def test_redact_output_suppresses_sensitive_command_spellings() -> None:
    """Environment, terminal, buffer, and history output stays off records."""
    from libtmux._internal.log_context import redact_output

    subcommands = (
        "show-environment",
        "showenv",
        "capture-pane",
        "capturep",
        "save-buffer",
        "saveb",
        "show-buffer",
        "showb",
        "list-buffers",
        "lsb",
        "show-messages",
        "showmsgs",
        "server-info",
        "info",
        "show-prompt-history",
        "showphist",
        "show-e",
        "ca",
        "sa",
        "show-b",
        "list-b",
        "show-m",
        "show-p",
    )
    for subcommand in subcommands:
        assert redact_output(subcommand, ["KEY=secret", "continuation"]) == []


@pytest.mark.parametrize(
    ("line_break", "escaped"),
    (
        ("\n", r"\n"),
        ("\x85", r"\u0085"),
        ("\u2028", r"\u2028"),
        ("\u2029", r"\u2029"),
    ),
)
def test_socket_identity_cannot_forge_a_log_line(
    line_break: str,
    escaped: str,
) -> None:
    """Socket identity stays scalar when tmux accepts a control character."""
    from libtmux._internal.log_context import describe_command

    context = describe_command(
        ["tmux", "-L", f"safe{line_break}ERROR libtmux forged", "list-sessions"],
    )

    assert context.socket is not None
    assert line_break not in context.socket
    assert escaped in context.socket
    assert context.socket.splitlines() == [context.socket]


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
    assert "$'echo hi\\nCRITICAL libtmux.server forged'" in rec.tmux_cmd


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


def test_oversized_command_is_capped_in_the_record(
    server: Server,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An oversized rejected command must not put its whole payload in the log."""
    from libtmux._internal.log_context import _COMMAND_CAP

    with (
        caplog.at_level(logging.DEBUG, logger="libtmux.common"),
        contextlib.suppress(Exception),
    ):
        server.cmd("list-sessions", "-F", "x" * (_COMMAND_CAP * 4))

    records = [r for r in caplog.records if hasattr(r, "tmux_cmd")]
    assert len(records) >= 1

    rec = t.cast(t.Any, records[0])
    assert len(rec.tmux_cmd) <= _COMMAND_CAP
    assert rec.tmux_cmd.endswith("\N{HORIZONTAL ELLIPSIS}")


def test_environment_values_are_hidden_in_both_directions(
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Redacting what libtmux sends is half of it; tmux hands the value back."""
    secret = "s3cr3t-round-trip"
    server = session.server
    server.set_environment("DEPLOY_KEY", secret)

    with caplog.at_level(logging.DEBUG, logger="libtmux.common"):
        value = server.getenv("DEPLOY_KEY")

    assert value == secret, "redaction must not change what the caller gets"

    leaked = [
        r
        for r in caplog.records
        for key in ("tmux_cmd", "tmux_stdout")
        if secret in str(getattr(r, key, ""))
    ]
    assert leaked == [], f"secret reached {len(leaked)} record(s)"


def test_multiline_environment_and_buffer_content_are_withheld(
    server: Server,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Known multiline and buffer content reaches callers, not records."""
    continuation = "logging-continuation-secret"
    buffer_content = "logging-buffer-secret"
    server.new_session(session_name="logging_sensitive_content")
    server.set_environment("DEPLOY_KEY", f"first\n{continuation}")

    with caplog.at_level(logging.DEBUG, logger="libtmux.common"):
        environment = server.cmd("show-environment", "-g", "DEPLOY_KEY")
        server.set_buffer(buffer_content)
        buffer = server.cmd("show-buffer")

    assert continuation in environment.stdout
    assert buffer.stdout == [buffer_content]
    leaked = [
        record
        for record in caplog.records
        for key in ("tmux_cmd", "tmux_stdout")
        if any(
            marker in str(getattr(record, key, ""))
            for marker in (continuation, buffer_content)
        )
    ]
    assert leaked == []


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

    records = [r for r in caplog.records if hasattr(r, "tmux_stdout")]
    assert records, "expected a completion record"
    for record in records:
        rec = t.cast(t.Any, record)
        assert not any(marker in line for line in rec.tmux_stdout)
        if rec.tmux_subcommand == "capture-pane":
            assert rec.tmux_stdout == []
            assert rec.tmux_stdout_len > 0, "the count still reports what came back"


def test_parse_failure_propagates_without_logging(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A parser failure remains exception data."""
    from libtmux.formats import FORMAT_SEPARATOR
    from libtmux.neo import parse_output

    row = FORMAT_SEPARATOR.join(["one", "two", "three"]) + FORMAT_SEPARATOR

    with (
        caplog.at_level(logging.ERROR, logger="libtmux.neo"),
        pytest.raises(ValueError, match="zip"),
    ):
        parse_output(row, "list-panes", "3.7")

    assert [
        record for record in caplog.records if record.levelno == logging.ERROR
    ] == []


def test_concurrent_records_share_no_mutable_state(
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
    assert {tuple(t.cast(t.Any, record).tmux_stdout) for record in completed} == {
        (marker,) for marker in markers
    }
    assert all(
        t.cast(t.Any, record).tmux_socket == server.socket_name for record in completed
    )

    containers = [
        (id(value), record.getMessage(), key)
        for record in caplog.records
        for key, value in record.__dict__.items()
        if key.startswith("tmux_") and isinstance(value, (list, dict))
    ]
    assert containers, "expected records carrying list-valued fields"

    identities = [identity for identity, _, _ in containers]
    assert len(identities) == len(set(identities)), (
        f"records share a mutable value: {containers}"
    )
