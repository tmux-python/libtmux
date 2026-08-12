"""Tests for :mod:`libtmux.engines`, the tmux command execution seam."""

from __future__ import annotations

import json
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
    Exchange,
    RecordingEngine,
    ReplayEngine,
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


def test_replay_hydrates_objects_without_a_tmux_binary(session: Session) -> None:
    """A tape answers listing queries on a machine with no tmux installed.

    The ``-F`` template is version-gated, so something must name a tmux version
    before a listing query can be built. Resolving that by running ``tmux -V``
    made replay depend on the very binary it exists to avoid, and the failure
    was silent: the lenient list accessors turned it into an empty result.
    """
    server = session.server
    recorder = RecordingEngine(SubprocessEngine.for_server(server))
    recording = Server(socket_name=server.socket_name, engine=recorder)
    assert [s.session_name for s in recording.sessions]

    tape = json.loads(json.dumps(recorder.to_dict()))
    assert tape["tmux_version"]

    offline = Server(
        socket_name=server.socket_name,
        tmux_bin="/nonexistent/tmux",
        engine=ReplayEngine.from_dict(tape),
    )
    assert [s.session_name for s in offline.sessions] == [
        s.session_name for s in recording.sessions
    ]


def test_unscripted_command_is_not_swallowed_by_list_accessors() -> None:
    """An incomplete tape raises rather than reporting "no sessions".

    ``Server.sessions`` is lenient by contract, but that contract covers a tmux
    that cannot be reached -- not an engine that was never taught to answer.
    """
    server = Server(
        tmux_bin="/nonexistent/tmux", engine=ReplayEngine({}, tmux_version="3.7")
    )
    with pytest.raises(exc.UnscriptedCommand) as excinfo:
        _ = server.sessions
    message = str(excinfo.value)
    assert "list-sessions" in message
    assert "3.7" in message
    # The -F template must be summarized, not dumped into the message.
    assert len(message) < 200


def test_replay_preserves_answers_that_changed(session: Session) -> None:
    """A command answered differently twice replays both answers, in order.

    A tape keyed only by argv would remember the last answer and report the end
    state for the earlier step, so a test asserting a transition would pass
    against the wrong value.
    """
    server = session.server
    recorder = RecordingEngine(SubprocessEngine.for_server(server))
    recording = Server(socket_name=server.socket_name, engine=recorder)

    before = len(recording.sessions)
    recording.new_session("replay_seq_extra")
    after = len(recording.sessions)
    assert after == before + 1

    offline = Server(
        socket_name=server.socket_name,
        tmux_bin="/nonexistent/tmux",
        engine=ReplayEngine.from_dict(json.loads(json.dumps(recorder.to_dict()))),
    )
    assert len(offline.sessions) == before
    assert len(offline.sessions) == after

    # The answer demonstrably varied, so there is no defensible reply to a
    # third call; guessing one is what this design exists to prevent.
    with pytest.raises(exc.UnscriptedCommand, match="asked 3 times now"):
        _ = offline.sessions


def test_replay_repeats_an_answer_that_never_varied() -> None:
    """A command recorded once may be replayed any number of times."""
    tape = [
        Exchange(
            ("display-message", "-p", "hi"),
            CommandResult(cmd=("tmux",), stdout=("hi",)),
        ),
    ]
    server = Server(engine=ReplayEngine(tape))
    assert [server.cmd("display-message", "-p", "hi").stdout[0] for _ in range(4)] == [
        "hi",
    ] * 4


def test_using_scopes_an_engine_to_a_block(session: Session) -> None:
    """``Server.using()`` swaps the engine for a block, then restores it."""
    server = session.server
    original = server.engine
    canned = CannedEngine(stdout=("scoped",))

    with server.using(canned) as scoped:
        assert scoped is server
        assert server.engine is canned
        assert server.cmd("display-message", "-p", "x").stdout == ["scoped"]

    assert server.engine is original
    assert server.cmd("display-message", "-p", "x").stdout != ["scoped"]


def test_using_restores_on_exception(session: Session) -> None:
    """A raise inside the block still restores the previous engine."""
    server = session.server
    original = server.engine

    with pytest.raises(ValueError, match="boom"), server.using(CannedEngine()):
        msg = "boom"
        raise ValueError(msg)

    assert server.engine is original


def test_using_nests(session: Session) -> None:
    """Nested scopes unwind in order."""
    server = session.server
    outer, inner = CannedEngine(stdout=("outer",)), CannedEngine(stdout=("inner",))

    with server.using(outer):
        assert server.cmd("x").stdout == ["outer"]
        with server.using(inner):
            assert server.cmd("x").stdout == ["inner"]
        assert server.cmd("x").stdout == ["outer"]


def test_using_validates_like_the_constructor(session: Session) -> None:
    """A non-engine is rejected where it is supplied, not on first command."""

    class OnlyRun:
        def run(self, request: CommandRequest) -> CommandResult:
            return CommandResult(cmd=("tmux",))

    with (
        pytest.raises(exc.LibTmuxException, match="run_batch"),
        session.server.using(OnlyRun()),  # type: ignore[arg-type]
    ):
        pass


def test_recording_captures_a_block(session: Session) -> None:
    """``Server.recording()`` records the block's traffic and restores after."""
    server = session.server
    original = server.engine

    with server.recording() as recorder:
        server.new_session("recording_ctx")
        assert [s.session_name for s in server.sessions]

    assert server.engine is original
    assert any(argv[0] == "new-session" for argv in recorder.requests)

    offline = Server(
        socket_name=server.socket_name,
        tmux_bin="/nonexistent/tmux",
        engine=ReplayEngine.from_dict(recorder.to_dict()),
    )
    assert [s.session_name for s in offline.sessions]
