"""Tests for :mod:`libtmux.engines`, the tmux command execution seam."""

from __future__ import annotations

import subprocess
import typing as t
import warnings

import pytest

from libtmux import exc
from libtmux.common import tmux_cmd
from libtmux.engines import (
    CommandRequest,
    CommandResult,
    CommandSeparator,
    ServerConnection,
    SubprocessEngine,
    SupportsCommandLine,
    SupportsTmuxVersion,
    TmuxEngine,
    encode_direct_argv,
    split_direct_argv,
)
from libtmux.neo import fetch_objs
from libtmux.server import Server
from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.session import Session


class CannedEngine:
    """An in-memory engine: records requests, replays canned stdout.

    Satisfies :class:`~libtmux.engines.base.TmuxEngine` structurally, without
    inheritance and without a tmux binary.
    """

    def __init__(self, stdout: Sequence[str] = ()) -> None:
        self.requests: list[CommandRequest] = []
        self._stdout = tuple(stdout)

    def run(self, request: CommandRequest) -> CommandResult:
        """Record *request* and return the canned result."""
        self.requests.append(request)
        return CommandResult(
            cmd=("canned-tmux", *request.args),
            stdout=self._stdout,
        )

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Run each request in order."""
        return [self.run(request) for request in requests]


def test_canned_engine_satisfies_protocol() -> None:
    """A plain class with run/run_batch is a TmuxEngine."""
    assert isinstance(CannedEngine(), TmuxEngine)
    assert not isinstance(CannedEngine(), SupportsCommandLine)
    assert not isinstance(CannedEngine(), SupportsTmuxVersion)


def test_server_drives_injected_engine_without_tmux() -> None:
    """``Server(engine=...)`` routes ``cmd()`` through the injected engine.

    No tmux fixture: the point is that an injected engine never forks tmux, so
    the canned stdout is what ``Server.cmd`` returns.
    """
    engine = CannedEngine(stdout=("$9",))
    server = Server(socket_name="canned_never_started", engine=engine)

    proc = server.cmd("new-session", "-P", "-F#{session_id}")

    assert proc.stdout == ["$9"]
    assert proc.returncode == 0
    assert proc.cmd == ["canned-tmux", "new-session", "-P", "-F#{session_id}"]
    assert [request.args for request in engine.requests] == [
        ("new-session", "-P", "-F#{session_id}"),
    ]
    assert server.engine is engine


def test_injected_engine_receives_target_flag() -> None:
    """``target=`` is rendered into the request, not the connection."""
    engine = CannedEngine()
    server = Server(socket_name="canned_target", engine=engine)

    server.cmd("kill-window", target="@3")

    assert engine.requests[0].args == ("kill-window", "-t", "@3")


def test_process_raises_on_engine_without_subprocess() -> None:
    """``.process`` is unavailable when no OS process was forked."""
    server = Server(socket_name="canned_process", engine=CannedEngine())
    proc = server.cmd("list-sessions")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(exc.LibTmuxException):
            _ = proc.process

    assert any(issubclass(entry.category, DeprecationWarning) for entry in caught)


def test_process_is_popen_under_default_engine(session: Session) -> None:
    """``.process`` still resolves to the Popen, with a DeprecationWarning."""
    proc = session.server.cmd("display-message", "-p", "hi")

    with pytest.deprecated_call():
        process = proc.process

    assert isinstance(process, subprocess.Popen)
    assert process.returncode == 0


def test_connection_follows_socket_name_mutation() -> None:
    """A post-construction write to ``socket_name`` changes the flags used.

    ``Server.socket_name`` is public and writable, so the connection is derived
    per command rather than captured at construction.
    """
    server = Server(socket_name="mutation_before")
    assert server.connection.args == ("-Lmutation_before",)
    first = server.connection

    server.socket_name = "mutation_after"

    assert server.connection.args == ("-Lmutation_after",)
    assert server.connection is not first
    assert server.cmd("has-session", "-t", "nothing").cmd[1] == "-Lmutation_after"


def test_connection_is_cached_while_unchanged(server: Server) -> None:
    """An untouched server reuses one connection, and so one binary lookup."""
    assert server.connection is server.connection
    assert server.engine is server.engine


def test_default_engine_rebuilt_after_mutation() -> None:
    """The default engine is rebuilt when the connection it wraps changes."""
    server = Server(socket_name="engine_rebuild_before")
    first = server.engine

    server.socket_name = "engine_rebuild_after"
    second = server.engine

    assert first is not second
    assert isinstance(second, SubprocessEngine)
    assert second.server_args == ("-Lengine_rebuild_after",)


def test_injected_engine_survives_mutation() -> None:
    """An injected engine is user-owned: libtmux never swaps it out."""
    engine = CannedEngine()
    server = Server(socket_name="injected_before", engine=engine)

    server.socket_name = "injected_after"

    assert server.engine is engine


class ArgvRecordingEngine:
    """Render argv against a real connection, record it, run nothing.

    Lets a test read the command line each dispatch path *would* have used,
    without a tmux server and without special-casing any one path.
    """

    def __init__(self, connection: ServerConnection) -> None:
        self.connection = connection
        self.command_lines: list[tuple[str, ...]] = []

    def run(self, request: CommandRequest) -> CommandResult:
        """Record the rendered argv and return an empty success."""
        cmd = (self.connection.tmux_bin or "tmux", *self.connection.args, *request.args)
        self.command_lines.append(cmd)
        return CommandResult(cmd=cmd)

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Run each request in order."""
        return [self.run(request) for request in requests]


def test_flag_builders_agree() -> None:
    """cmd(), raise_if_dead() and fetch_objs() emit identical flags.

    All three paths formerly built ``-L``/``-S``/``-f``/``-2`` themselves, from
    three different rules. They now read one
    :class:`~libtmux.engines.connection.ServerConnection`.
    """
    attrs: dict[str, t.Any] = {
        "socket_name": "flag_agreement",
        "config_file": "/dev/null",
        "colors": 256,
    }
    expected = Server(**attrs).connection.args
    assert expected == ("-2", "-f/dev/null", "-Lflag_agreement")

    engine = ArgvRecordingEngine(Server(**attrs).connection)
    server = Server(**attrs, engine=engine)

    server.cmd("list-sessions")
    server.raise_if_dead()
    fetch_objs(server=server, list_cmd="list-sessions")

    assert len(engine.command_lines) == 3
    assert {line[1 : 1 + len(expected)] for line in engine.command_lines} == {expected}


def test_unknown_color_raises_on_every_path() -> None:
    """An unknown ``colors`` value raises, matching ``Server.cmd``'s contract."""
    server = Server(socket_name="bad_colors")
    server.colors = 16

    with pytest.raises(exc.UnknownColorOption):
        server.cmd("list-sessions")
    with pytest.raises(exc.UnknownColorOption):
        server.raise_if_dead()
    with pytest.raises(exc.UnknownColorOption):
        fetch_objs(server=server, list_cmd="list-sessions")


def test_trailing_semicolon_is_literal(session: Session) -> None:
    """A trailing ``";"`` reaches tmux as data, not as a command boundary.

    Unescaped, tmux's argv parser reads the final ``;`` as a separator and the
    pane never sees it.
    """
    window = session.new_window(window_name="semicolon")
    pane = window.active_pane
    assert pane is not None

    pane.send_keys("echo one;", literal=True, enter=False)

    def typed() -> bool:
        return any(line.endswith("echo one;") for line in pane.capture_pane())

    assert retry_until(typed, raises=False), pane.capture_pane()


def test_command_separator_stays_structural(session: Session) -> None:
    """An explicit :class:`CommandSeparator` still separates two commands."""
    server = session.server
    proc = server.cmd(
        "display-message",
        "-p",
        "first",
        CommandSeparator(";"),
        "display-message",
        "-p",
        "second",
    )

    assert proc.stdout == ["first", "second"]


def test_encode_direct_argv_leaves_global_values_alone() -> None:
    """Connection-flag values are data to tmux's getopt, never separators."""
    assert encode_direct_argv(("-L", "sock;", "send-keys", "text;")) == (
        "-L",
        "sock;",
        "send-keys",
        "text\\;",
    )
    assert split_direct_argv(("-2", "-f/tmp/c", "list-sessions")).command_argv == (
        "list-sessions",
    )


def test_command_request_rejects_nul() -> None:
    """NUL cannot survive tmux's C-string argv."""
    with pytest.raises(ValueError, match="NUL"):
        CommandRequest.from_args("display-message", "a\0b")


def test_connection_from_server_duck_types() -> None:
    """``from_server`` reads any object with the five connection attributes."""
    conn = ServerConnection.from_server(
        Server(socket_path="/tmp/spike-sock", config_file="/tmp/spike-conf"),
    )
    assert conn.args == ("-f/tmp/spike-conf", "-S/tmp/spike-sock")


def test_subprocess_engine_reports_version(session: Session) -> None:
    """The default engine can answer ``tmux -V`` for version gating."""
    engine = SubprocessEngine.for_server(session.server)
    assert isinstance(engine, SupportsTmuxVersion)
    assert engine.tmux_version() == engine.tmux_version()
    assert engine.tmux_version() is not None


def test_missing_binary_raises_tmux_command_not_found() -> None:
    """A declared-but-absent tmux binary raises, on every path."""
    engine = SubprocessEngine.of("/nonexistent/tmux")
    with pytest.raises(exc.TmuxCommandNotFound):
        engine.run(CommandRequest.from_args("list-sessions"))
    with pytest.raises(exc.TmuxCommandNotFound):
        tmux_cmd("list-sessions", tmux_bin="/nonexistent/tmux")


def test_run_batch_preserves_order(session: Session) -> None:
    """``run_batch`` returns one result per request, in order."""
    results = SubprocessEngine.for_server(session.server).run_batch(
        [
            CommandRequest.from_args("display-message", "-p", "a"),
            CommandRequest.from_args("display-message", "-p", "b"),
        ],
    )
    assert [result.stdout[0] for result in results] == ["a", "b"]
