"""Tests for libtmux logging contracts."""

from __future__ import annotations

import errno
import logging
import os
import pathlib
import shlex
import sys
import typing as t
from collections.abc import Callable

import pytest

if t.TYPE_CHECKING:
    from libtmux._internal.control_mode import ControlMode
    from libtmux.server import Server
    from libtmux.session import Session


def _capture_info(
    caplog: pytest.LogCaptureFixture,
    logger_name: str,
    message: str,
    action: Callable[[], object],
) -> tuple[t.Any, t.Any]:
    """Run one action and return its single matching lifecycle record."""
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=logger_name):
        result = action()

    records = [
        record
        for record in caplog.records
        if record.levelno == logging.INFO and record.getMessage() == message
    ]
    assert len(records) == 1
    return result, t.cast(t.Any, records[0])


def test_tmux_cmd_debug_logging_schema(
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Command records expose the command and bounded output snapshots."""
    server = session.server
    marker = "caller-payload"

    with caplog.at_level(logging.DEBUG, logger="libtmux.common"):
        proc = server.cmd("list-sessions", "-F", marker)

    assert marker in proc.stdout
    records = [
        record
        for record in caplog.records
        if record.getMessage().startswith("tmux command")
    ]
    assert [record.getMessage() for record in records] == [
        "tmux command dispatched",
        "tmux command completed",
    ]
    for record in records:
        rec = t.cast(t.Any, record)
        assert rec.tmux_subcommand == "list-sessions"
        assert rec.tmux_socket == server.socket_name
        assert rec.tmux_cmd.endswith(f"list-sessions -F {marker}")

    dispatched = t.cast(t.Any, records[0])
    assert not hasattr(dispatched, "tmux_stdout")
    assert not hasattr(dispatched, "tmux_stderr")
    completed = t.cast(t.Any, records[-1])
    assert isinstance(completed.tmux_exit_code, int)
    assert completed.tmux_stdout == proc.stdout
    assert completed.tmux_stderr == proc.stderr
    assert completed.tmux_stdout_len == len(proc.stdout)
    assert completed.tmux_stderr_len == 0


def test_tmux_cmd_debug_logging_bounds_large_output(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Completion records retain 100 lines and report the full stream lengths."""
    from libtmux.common import tmux_cmd

    stdout_lines = [f"stdout-{index}-π-\x1b[31m" for index in range(150)]
    stderr_lines = [f"stderr-{index}-π-\x1b[31m" for index in range(150)]
    script = (
        "import sys\n"
        "for index in range(150):\n"
        " print(f'stdout-{index}-π-\\x1b[31m')\n"
        " print(f'stderr-{index}-π-\\x1b[31m', file=sys.stderr)\n"
    )

    with caplog.at_level(logging.DEBUG, logger="libtmux.common"):
        proc = tmux_cmd("-c", script, tmux_bin=sys.executable)

    completed = t.cast(
        t.Any,
        next(
            record
            for record in caplog.records
            if record.getMessage() == "tmux command completed"
        ),
    )
    assert proc.stdout == stdout_lines
    assert proc.stderr == stderr_lines
    assert completed.tmux_stdout == stdout_lines[:100]
    assert completed.tmux_stderr == stderr_lines[:100]
    assert completed.tmux_stdout_len == 150
    assert completed.tmux_stderr_len == 150


def test_control_mode_debug_logging_keeps_command_context(
    control_mode: Callable[[], ControlMode],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Control mode exposes the spawned command and structured target fields."""
    with (
        caplog.at_level(logging.DEBUG, logger="libtmux._internal.control_mode"),
        control_mode() as client,
    ):
        target = str(client.session.session_id)

    record = t.cast(
        t.Any,
        next(
            record
            for record in caplog.records
            if record.getMessage() == "control mode client started"
        ),
    )
    assert record.tmux_subcommand == "attach-session"
    assert record.tmux_target == target
    assert "-C attach-session -t" in record.tmux_cmd
    assert shlex.split(record.tmux_cmd)[-1] == target


def test_lifecycle_info_logging(
    server: Server,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Lifecycle call sites emit the shared string-valued context schema."""
    from libtmux._internal.log_context import object_extra
    from libtmux.test.random import namer

    session_name = f"log_session_{next(namer)}"
    renamed_session = f"log_session_{next(namer)}"
    window_name = f"log_window_{next(namer)}"
    renamed_window = f"log_window_{next(namer)}"

    session, session_created = _capture_info(
        caplog,
        "libtmux.server",
        "session created",
        lambda: server.new_session(session_name=session_name),
    )
    _, session_renamed = _capture_info(
        caplog,
        "libtmux.session",
        "session renamed",
        lambda: session.rename_session(renamed_session),
    )
    window, window_created = _capture_info(
        caplog,
        "libtmux.session",
        "window created",
        lambda: session.new_window(window_name=window_name),
    )
    _, window_renamed = _capture_info(
        caplog,
        "libtmux.window",
        "window renamed",
        lambda: window.rename_window(renamed_window),
    )
    pane = window.active_pane
    assert pane is not None
    split_pane, pane_created = _capture_info(
        caplog,
        "libtmux.pane",
        "pane created",
        pane.split,
    )
    _, pane_killed = _capture_info(
        caplog,
        "libtmux.pane",
        "pane killed",
        split_pane.kill,
    )
    _, window_killed = _capture_info(
        caplog,
        "libtmux.session",
        "window killed",
        lambda: session.kill_window(window.window_id),
    )
    doomed_name = f"log_session_{next(namer)}"
    doomed, _ = _capture_info(
        caplog,
        "libtmux.server",
        "session created",
        lambda: server.new_session(session_name=doomed_name),
    )
    _, session_killed = _capture_info(
        caplog,
        "libtmux.server",
        "session killed",
        lambda: server.kill_session(doomed_name),
    )

    records = [
        session_created,
        session_renamed,
        window_created,
        window_renamed,
        pane_created,
        pane_killed,
        window_killed,
        session_killed,
    ]
    assert [
        (record.name, record.getMessage(), record.tmux_subcommand) for record in records
    ] == [
        ("libtmux.server", "session created", "new-session"),
        ("libtmux.session", "session renamed", "rename-session"),
        ("libtmux.session", "window created", "new-window"),
        ("libtmux.window", "window renamed", "rename-window"),
        ("libtmux.pane", "pane created", "split-window"),
        ("libtmux.pane", "pane killed", "kill-pane"),
        ("libtmux.session", "window killed", "kill-window"),
        ("libtmux.server", "session killed", "kill-session"),
    ]
    for record in records:
        assert record.tmux_socket == server.socket_name
        for key in (
            "tmux_subcommand",
            "tmux_socket",
            "tmux_session",
            "tmux_window",
            "tmux_pane",
            "tmux_target",
        ):
            value = getattr(record, key, None)
            assert value is None or isinstance(value, str)

    assert session_created.tmux_session == session_name
    assert session_renamed.tmux_session == renamed_session
    assert window_created.tmux_window == window_name
    assert window_renamed.tmux_window == renamed_window
    assert pane_created.tmux_pane == split_pane.pane_id
    assert pane_killed.tmux_pane == split_pane.pane_id
    assert window_killed.tmux_target == window.window_id
    assert session_killed.tmux_target == doomed.session_name
    assert (
        object_extra("kill-session", target="safe\u2028ERROR forged")["tmux_target"]
        == "'safe\\u2028ERROR forged'"
    )


def test_all_except_lifecycle_logging(
    server: Server,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The three all-except branches identify the object they preserve."""
    from libtmux.test.random import namer

    workspace = server.new_session(session_name=f"log_workspace_{next(namer)}")
    window = workspace.new_window(window_name=f"log_window_{next(namer)}")
    workspace.new_window(window_name=f"log_other_{next(namer)}")
    _, windows_killed = _capture_info(
        caplog,
        "libtmux.window",
        "other windows killed",
        lambda: window.kill(all_except=True),
    )

    window.resize(height=100, width=100)
    pane = window.split()
    window.split()
    _, panes_killed = _capture_info(
        caplog,
        "libtmux.pane",
        "other panes killed",
        lambda: pane.kill(all_except=True),
    )

    survivor = server.new_session(session_name=f"log_survivor_{next(namer)}")
    server.new_session(session_name=f"log_other_{next(namer)}")
    _, sessions_killed = _capture_info(
        caplog,
        "libtmux.session",
        "other sessions killed",
        lambda: survivor.kill(all_except=True),
    )

    assert (
        windows_killed.tmux_subcommand,
        windows_killed.tmux_window,
        windows_killed.tmux_target,
    ) == ("kill-window", window.window_name, window.window_id)
    assert (
        panes_killed.tmux_subcommand,
        panes_killed.tmux_pane,
        panes_killed.tmux_target,
    ) == ("kill-pane", pane.pane_id, pane.pane_id)
    assert (
        sessions_killed.tmux_subcommand,
        sessions_killed.tmux_session,
        sessions_killed.tmux_target,
    ) == ("kill-session", survivor.session_name, survivor.session_id)


def test_server_kill_info_logging(caplog: pytest.LogCaptureFixture) -> None:
    """Killing a server emits its lifecycle record."""
    from libtmux.server import Server
    from libtmux.test.random import namer

    with Server(socket_name=f"libtmux_log_{next(namer)}") as server:
        server.new_session(session_name=f"log_session_{next(namer)}")
        _, record = _capture_info(
            caplog,
            "libtmux.server",
            "server killed",
            server.kill,
        )

    assert record.tmux_subcommand == "kill-server"
    assert record.tmux_socket == server.socket_name


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
    """A translated environment failure remains exception data only."""
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


@pytest.mark.parametrize(
    "binary_case",
    ["configured-missing", "default-missing", "not-executable", "invalid-format"],
)
def test_unusable_tmux_binary_propagates_without_logging(
    binary_case: str,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unusable executable remains exception data, not a log record."""
    from libtmux import exc
    from libtmux.common import tmux_cmd

    tmux_path = tmp_path / "tmux"
    tmux_bin: str | None = str(tmux_path)
    if binary_case == "default-missing":
        tmux_bin = None
        monkeypatch.setattr("libtmux.common.shutil.which", lambda _: None)
    elif binary_case in {"not-executable", "invalid-format"}:
        tmux_path.write_text("not an executable format\n")
        tmux_path.chmod(0o644 if binary_case == "not-executable" else 0o755)
    with (
        caplog.at_level(logging.ERROR, logger="libtmux.common"),
        pytest.raises(exc.TmuxCommandNotFound),
    ):
        tmux_cmd("list-sessions", tmux_bin=tmux_bin)

    assert [
        record for record in caplog.records if record.levelno == logging.ERROR
    ] == []


def test_unrelated_tmux_launch_failure_preserves_diagnostics() -> None:
    """A launch resource failure is not mislabeled as a missing executable."""
    from libtmux import exc
    from libtmux.common import tmux_cmd

    with pytest.raises(exc.LibTmuxException) as exc_info:
        tmux_cmd("set-buffer", "x" * os.sysconf("SC_ARG_MAX"))

    assert not isinstance(exc_info.value, exc.TmuxCommandNotFound)
    cause = exc_info.value.__cause__
    assert isinstance(cause, OSError)
    assert cause.errno == errno.E2BIG
    assert str(exc_info.value) == str(cause)


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
    """A health check converts an unusable executable to a quiet false result."""
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
    """Malformed values produce one aggregate warning without traceback data."""
    from libtmux._internal.sparse_array import SparseArray
    from libtmux.options import explode_complex

    bad_features: SparseArray[str | int | bool | None] = SparseArray()
    for index in range(25):
        bad_features[index] = index

    with caplog.at_level(logging.WARNING, logger="libtmux.options"):
        explode_complex({"terminal-features": bad_features})  # type: ignore[dict-item]

    records = [
        record
        for record in caplog.records
        if getattr(record, "tmux_option_key", None) == "terminal-features"
    ]
    assert len(records) == 1
    record = t.cast(t.Any, records[0])
    assert record.tmux_option_skipped == 25
    assert record.exc_info is None


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (
            ["tmux", "-Lsock", "new-session", "-eKEY=secret"],
            {
                "tmux_cmd": "tmux -Lsock new-session -eKEY=secret",
                "tmux_subcommand": "new-session",
                "tmux_socket": "sock",
            },
        ),
        (
            ["tmux", "-S", "/tmp/s", "set-buffer", "secret"],
            {
                "tmux_cmd": "tmux -S /tmp/s set-buffer secret",
                "tmux_subcommand": "set-buffer",
                "tmux_socket": "/tmp/s",
            },
        ),
        (
            ["tmux", "-f", "secret-conf", "run-shell", "secret"],
            {
                "tmux_cmd": "tmux -f secret-conf run-shell secret",
                "tmux_subcommand": "run-shell",
            },
        ),
        (
            ["tmux", "-2L", "sock", "list-panes"],
            {
                "tmux_cmd": "tmux -2L sock list-panes",
                "tmux_subcommand": "list-panes",
                "tmux_socket": "sock",
            },
        ),
        (
            ["tmux", "-L", "safe\nforged", "future-command", "secret"],
            {
                "tmux_cmd": "tmux -L 'safe\\nforged' future-command secret",
                "tmux_subcommand": "future-command",
                "tmux_socket": "'safe\\nforged'",
            },
        ),
        (
            ["tmux", "-Z", "operand-secret"],
            {
                "tmux_cmd": "tmux -Z operand-secret",
            },
        ),
        (
            ["tmux", "--future-option=value", "list-sessions", "payload"],
            {
                "tmux_cmd": "tmux --future-option=value list-sessions payload",
            },
        ),
        (
            ["tmux", "--", "future-command", "payload"],
            {
                "tmux_cmd": "tmux -- future-command payload",
                "tmux_subcommand": "future-command",
            },
        ),
        (["tmux", "-V"], {"tmux_cmd": "tmux -V"}),
    ],
)
def test_command_extra_preserves_command_and_extracts_context(
    argv: list[str],
    expected: dict[str, str],
) -> None:
    """Command records retain argv while deriving optional structured fields."""
    from libtmux._internal.log_context import command_extra

    assert command_extra(argv) == expected


@pytest.mark.parametrize("flag", tuple("2CDdhlNquUvV"))
def test_command_extra_parses_boolean_global_flags(flag: str) -> None:
    """Known boolean flags leave the following token as the subcommand."""
    from libtmux._internal.log_context import command_extra

    result = command_extra(["tmux", f"-{flag}", "list-sessions"])

    assert result["tmux_subcommand"] == "list-sessions"


@pytest.mark.parametrize("flag", tuple("cfLST"))
@pytest.mark.parametrize("attached", [False, True])
def test_command_extra_parses_value_global_flags(
    flag: str,
    attached: bool,
) -> None:
    """Known value flags accept attached and separate values."""
    from libtmux._internal.log_context import command_extra

    option = f"-{flag}value" if attached else f"-{flag}"
    argv = ["tmux", option]
    if not attached:
        argv.append("value")
    argv.append("list-sessions")

    result = command_extra(argv)

    assert result["tmux_subcommand"] == "list-sessions"
    if flag in "LS":
        assert result["tmux_socket"] == "value"


def test_command_extra_preserves_unicode_and_escapes_controls() -> None:
    """Printable Unicode remains readable and controls cannot forge log lines."""
    from libtmux._internal.log_context import command_extra

    payload = "snowman ☃ and Ελληνικά"
    result = command_extra(
        ["tmux", "set-buffer", payload, "line\nERROR forged", "nul\0byte"]
    )

    assert payload in result["tmux_cmd"]
    assert "\n" not in result["tmux_cmd"]
    assert "\\nERROR forged" in result["tmux_cmd"]
    assert "\\x00" in result["tmux_cmd"]


def test_command_extra_preserves_large_operand() -> None:
    """Command logging does not truncate a large argv operand."""
    from libtmux._internal.log_context import command_extra

    payload = "x" * 1_000_000
    result = command_extra(["tmux", "set-buffer", payload])

    assert result["tmux_cmd"].endswith(payload)
    assert len(result["tmux_cmd"]) == len(payload) + len("tmux set-buffer ")


def test_session_fixture_setup_logs_no_errors(
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The bundled fixture does not inject ERROR records into test reports."""
    assert session.session_name is not None
    assert [
        record
        for record in caplog.get_records("setup")
        if record.levelno >= logging.ERROR
    ] == []


def test_lookup_path_cannot_forge_a_log_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A caller-provided lookup path remains one diagnostic line."""
    from libtmux._internal.query_list import keygetter

    with caplog.at_level(logging.DEBUG, logger="libtmux._internal.query_list"):
        keygetter({}, "missing\nERROR libtmux forged")

    record = caplog.records[-1]
    assert "\n" not in record.getMessage()
    assert "\\nERROR libtmux forged" in record.getMessage()


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

    assert [
        record for record in caplog.records if record.levelno == logging.ERROR
    ] == []
