"""Tests for :mod:`libtmux.engines`, the tmux command execution seam."""

from __future__ import annotations

import asyncio
import gc
import logging
import os
import signal
import subprocess
import time
import typing as t

import pytest

from libtmux import exc
from libtmux.common import tmux_cmd
from libtmux.engines import (
    CommandRequest,
    CommandResult,
    ServerConnection,
    SubprocessEngine,
    SupportsCommandLine,
    TmuxEngine,
)
from libtmux.neo import fetch_objs
from libtmux.pane import Pane
from libtmux.server import Server
from libtmux.session import Session
from libtmux.window import Window

if t.TYPE_CHECKING:
    import pathlib
    from collections.abc import Sequence


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

    with pytest.warns(DeprecationWarning), pytest.raises(exc.LibTmuxException):
        _ = proc.process


class ForeignResult(t.NamedTuple):
    """A result shaped like :class:`CommandResult` but of another type.

    An out-of-tree engine has no reason to import libtmux's result class, and
    :class:`~libtmux.engines.base.TmuxEngine` never says it must. ``process`` is
    absent here on purpose: it is the one field no protocol declares.
    """

    cmd: tuple[str, ...]
    stdout: tuple[str, ...] = ()
    stderr: tuple[str, ...] = ()
    returncode: int = 0


class ForeignResultEngine:
    """An engine returning a result type libtmux does not own."""

    def run(self, request: CommandRequest) -> t.Any:
        """Return a structurally-compatible result of a foreign type."""
        return ForeignResult(cmd=("foreign-tmux", *request.args), stdout=("$7",))

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[t.Any]:
        """Run each request in order."""
        return [self.run(request) for request in requests]


def test_server_drives_engine_returning_a_foreign_result() -> None:
    """An engine may return any structurally-compatible result, not only ours.

    ``TmuxEngine`` is structural, so an out-of-tree engine that never imports
    :class:`CommandResult` still qualifies. Reading ``process`` off such a
    result must degrade to the documented exception rather than raising
    :exc:`AttributeError` from inside dispatch.
    """
    server = Server(socket_name="foreign_result", engine=ForeignResultEngine())

    proc = server.cmd("new-session", "-P", "-F#{session_id}")

    assert proc.stdout == ["$7"]
    assert proc.returncode == 0
    assert proc.cmd == ["foreign-tmux", "new-session", "-P", "-F#{session_id}"]
    with pytest.warns(DeprecationWarning), pytest.raises(exc.LibTmuxException):
        _ = proc.process


def test_process_is_popen_under_default_engine(session: Session) -> None:
    """``.process`` reads exactly as it did before the seam existed."""
    proc = session.server.cmd("display-message", "-p", "hi")

    with pytest.warns(DeprecationWarning, match="tmux_cmd.process is deprecated"):
        process = proc.process

    assert isinstance(process, subprocess.Popen)
    assert process.returncode == 0


def test_result_ok_follows_returncode() -> None:
    """``ok`` is true exactly when tmux exited zero."""
    assert CommandResult(cmd=("tmux", "list-sessions")).ok
    assert not CommandResult(cmd=("tmux", "kill-window"), returncode=1).ok


def test_raise_for_status_carries_the_failure(server: Server) -> None:
    """A real tmux rejection becomes ``TmuxCommandError`` with its data."""
    engine = SubprocessEngine.for_server(server)
    result = engine.run(CommandRequest.from_args("kill-window", "-t", "@999"))

    with pytest.raises(exc.TmuxCommandError) as excinfo:
        result.raise_for_status()

    assert excinfo.value.returncode == result.returncode != 0
    assert excinfo.value.stderr == result.stderr
    assert excinfo.value.cmd == result.cmd
    assert isinstance(excinfo.value, exc.LibTmuxException)


def test_raise_for_status_passes_on_success(server: Server) -> None:
    """A zero exit does not raise."""
    engine = SubprocessEngine.for_server(server)
    engine.run(CommandRequest.from_args("new-session", "-d")).raise_for_status()


def test_cmd_stays_the_adapter_not_the_result(session: Session) -> None:
    """``Server.cmd()`` returns ``tmux_cmd`` (lists), never the frozen result."""
    proc = session.server.cmd("display-message", "-p", "hi")

    assert type(proc) is tmux_cmd
    assert proc.stdout == ["hi"]
    assert not isinstance(proc, CommandResult)


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
    assert server.cmd("has-session", "-t", "nothing").cmd[2] == "-Lmutation_after"


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


def test_engine_carrying_only_a_binary_still_adopts_the_socket() -> None:
    """A tmux binary names a *program*, not a server, so the socket still binds.

    Left unbound, such an engine runs ``<custom tmux> list-sessions`` with no
    ``-L``, reaching whichever server a flagless tmux finds rather than this
    one -- the silent ambient dispatch adoption exists to prevent.
    """
    engine = SubprocessEngine.of(tmux_bin="/nonexistent/tmux")
    server = Server(socket_name="bin_only_adopts", engine=engine)

    adopted = server.engine

    assert isinstance(adopted, SubprocessEngine)
    assert adopted.command_line(CommandRequest.from_args("list-sessions")) == (
        "/nonexistent/tmux",
        "-u",
        "-Lbin_only_adopts",
        "list-sessions",
    )


def test_adoption_keeps_the_engines_own_binary() -> None:
    """Adoption takes the server's flags without discarding the engine's binary."""
    engine = SubprocessEngine.of(tmux_bin="/nonexistent/tmux")
    server = Server(socket_name="bin_kept", tmux_bin="/other/tmux", engine=engine)

    adopted = server.engine

    assert isinstance(adopted, SubprocessEngine)
    assert adopted.tmux_bin == "/nonexistent/tmux"
    assert adopted.server_args == ("-Lbin_kept",)


def test_server_binary_reaches_an_engine_that_declares_none() -> None:
    """An engine with no binary of its own still inherits the server's."""
    server = Server(
        socket_name="bin_inherited",
        tmux_bin="/other/tmux",
        engine=SubprocessEngine(),
    )

    adopted = server.engine

    assert isinstance(adopted, SubprocessEngine)
    assert adopted.tmux_bin == "/other/tmux"
    assert adopted.server_args == ("-Lbin_inherited",)


def test_engine_naming_a_server_is_left_alone() -> None:
    """Connection flags of the engine's own win over the server's."""
    engine = SubprocessEngine.of(server_args=("-Lelsewhere",))
    server = Server(socket_name="not_elsewhere", engine=engine)

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


def test_raise_if_dead_carries_tmuxs_message() -> None:
    """The dead-server diagnostic rides on the exception instead of vanishing.

    The engine captures tmux's stderr rather than letting it reach the
    terminal, so dropping it would leave the caller with an exit code and
    nothing to explain it.
    """
    server = Server(socket_name="raise_if_dead_message")

    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        server.raise_if_dead()

    assert excinfo.value.stderr is not None
    assert "raise_if_dead_message" in excinfo.value.stderr


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


class AsyncEngine:
    """Structurally a :class:`TmuxEngine`, but both methods are ``async def``.

    ``TmuxEngine`` checks attribute names only, so this still satisfies
    ``isinstance(..., TmuxEngine)``.
    """

    async def run(self, request: CommandRequest) -> CommandResult:
        """Never actually awaited by libtmux; dispatch must reject this."""
        return CommandResult(cmd=("tmux", *request.args))

    async def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Unused by any in-tree dispatch path."""
        return [CommandResult(cmd=("tmux", *r.args)) for r in requests]


def _async_engine() -> TmuxEngine:
    """Hand back an :class:`AsyncEngine`, typed as a plain ``TmuxEngine``.

    ``AsyncEngine`` does not satisfy ``TmuxEngine`` *statically* -- its
    methods return ``Coroutine``, not the protocol's declared return types --
    which is exactly what makes the bug this module tests real: a type
    checker would reject it, but ``isinstance()`` at runtime does not. The
    cast documents that gap instead of hiding it behind a broader type on
    ``AsyncEngine`` itself.
    """
    return t.cast("TmuxEngine", AsyncEngine())


def test_async_engine_run_raises_named_error() -> None:
    """``run()`` returning an awaitable raises ``AsyncEngineMismatch``.

    Not ``AttributeError`` from treating a coroutine as a
    :class:`CommandResult`.
    """
    server = Server(socket_name="async_engine_run", engine=_async_engine())

    with pytest.raises(exc.AsyncEngineMismatch):
        server.cmd("list-sessions")


def test_async_engine_raise_if_dead_raises_the_same_error() -> None:
    """``raise_if_dead()`` shares :meth:`Server.cmd`'s single dispatch site.

    It no longer calls ``self.engine.run()`` on its own, so it inherits the
    guard instead of needing a second copy of it.
    """
    server = Server(socket_name="async_engine_dead", engine=_async_engine())

    with pytest.raises(exc.AsyncEngineMismatch):
        server.raise_if_dead()


def test_async_engine_fetch_objs_raises_the_same_error() -> None:
    """:func:`~libtmux.neo.fetch_objs` dispatches through the same guard."""
    server = Server(socket_name="async_engine_fetch_objs", engine=_async_engine())

    with pytest.raises(exc.AsyncEngineMismatch):
        fetch_objs(server=server, list_cmd="list-sessions")


class AsyncCommandLineEngine:
    """A synchronous ``run()`` paired with an asynchronous ``command_line()``.

    Isolates the DEBUG-log-only dispatch site: ``command_line()`` is only
    ever called to render the log line in :class:`tmux_cmd`, never to build
    the actual result.
    """

    def run(self, request: CommandRequest) -> CommandResult:
        """Behave like an ordinary synchronous engine."""
        return CommandResult(cmd=("tmux", *request.args))

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Run each request in order."""
        return [self.run(r) for r in requests]

    async def command_line(self, request: CommandRequest) -> tuple[str, ...]:
        """Return the argv, the one async method on an otherwise sync engine."""
        return ("tmux", *request.args)


def test_async_command_line_raises_named_error_under_debug_logging(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``command_line()`` only runs when DEBUG logging is enabled.

    Previously this bypassed the guard entirely and raised
    ``TypeError: 'coroutine' object is not iterable`` from ``shlex.join``.
    """
    server = Server(
        socket_name="async_command_line",
        engine=AsyncCommandLineEngine(),
    )

    with (
        caplog.at_level(logging.DEBUG, logger="libtmux.common"),
        pytest.raises(exc.AsyncEngineMismatch),
    ):
        server.cmd("list-sessions")


@pytest.mark.parametrize("attr", ["sessions", "clients", "attached_sessions"])
def test_async_engine_list_accessors_do_not_swallow_the_error(attr: str) -> None:
    """``AsyncEngineMismatch`` is not a tmux failure, so it is not lenient here.

    :attr:`Server.sessions`, :attr:`Server.clients`, and
    :attr:`Server.attached_sessions` return an empty
    :class:`~libtmux._internal.query_list.QueryList` for an actual tmux
    failure (no daemon, bad socket, permission error). An engine that cannot
    be dispatched synchronously at all is a different kind of problem --
    surfacing it as "no sessions" would hide a broken engine behind a
    misleading empty result.
    """
    server = Server(socket_name=f"async_engine_{attr}", engine=_async_engine())

    with pytest.raises(exc.AsyncEngineMismatch):
        getattr(server, attr)


class HostileGetattrAwaitable:
    """An awaitable that detonates on any ``close``/``cancel`` lookup.

    Cleanup that reached for those attributes would surface this object's
    ``RuntimeError`` in place of the diagnostic, which is the failure mode
    the guard's shape exists to avoid.
    """

    def __await__(self) -> t.Generator[None, None, None]:
        """Satisfy :func:`inspect.isawaitable` without ever being awaited."""
        yield

    def __getattr__(self, name: str) -> t.Any:
        """Raise for the cleanup lookups, ``AttributeError`` for the rest."""
        if name in {"close", "cancel"}:
            msg = "cleanup lookup blew up"
            raise RuntimeError(msg)
        raise AttributeError(name)


class HostileCloseCoroutine:
    """An awaitable whose ``close()`` raises a :class:`BaseException`.

    :exc:`asyncio.CancelledError` derives from :class:`BaseException`, not
    :class:`Exception`, so an ``except Exception`` around cleanup would let
    it escape and mask the diagnostic.
    """

    def __await__(self) -> t.Generator[None, None, None]:
        """Satisfy :func:`inspect.isawaitable` without ever being awaited."""
        yield

    def close(self) -> None:
        """Raise the exception an ``except Exception`` would not catch."""
        raise asyncio.CancelledError


def _engine_returning(value: t.Any) -> TmuxEngine:
    """Build a sync engine whose ``run()`` hands back *value*."""

    class Returns:
        def run(self, request: CommandRequest) -> t.Any:
            return value

        def run_batch(self, requests: Sequence[CommandRequest]) -> t.Any:
            return [value for _ in requests]

    return t.cast("TmuxEngine", Returns())


@pytest.mark.parametrize(
    "awaitable",
    [HostileGetattrAwaitable(), HostileCloseCoroutine()],
    ids=["hostile-getattr", "cancelled-error-on-close"],
)
def test_hostile_awaitable_cannot_mask_the_mismatch(awaitable: t.Any) -> None:
    """A hostile awaitable never replaces the diagnostic with its own error.

    Only genuine coroutines are closed, and that close is guarded against
    :class:`BaseException`, so neither an exploding attribute lookup nor a
    :exc:`asyncio.CancelledError` reaches the caller.
    """
    server = Server(
        socket_name="hostile_awaitable", engine=_engine_returning(awaitable)
    )

    with pytest.raises(exc.AsyncEngineMismatch):
        server.cmd("list-sessions")


async def _never_awaited() -> None:
    """Do nothing; this body must never run."""


class ReturnsCoroutineEngine:
    """A plain ``def`` engine that manufactures a coroutine anyway.

    The shape CPython documents as uncatchable by a callable-level check --
    ``run`` is not declared ``async``, so only its return value gives it away.
    """

    def run(self, request: CommandRequest) -> t.Any:
        """Hand back an unstarted coroutine instead of a result."""
        return _never_awaited()

    def run_batch(self, requests: Sequence[CommandRequest]) -> t.Any:
        """Hand back one unstarted coroutine per request."""
        return [_never_awaited() for _ in requests]


@pytest.mark.parametrize(
    ("label", "engine_factory"),
    [
        ("declared-async", _async_engine),
        ("returns-coroutine", lambda: t.cast("TmuxEngine", ReturnsCoroutineEngine())),
    ],
)
def test_no_never_awaited_warning_escapes(
    label: str,
    engine_factory: t.Callable[[], TmuxEngine],
    recwarn: pytest.WarningsRecorder,
) -> None:
    """Neither async shape leaves a ``coroutine ... was never awaited`` behind.

    A declared ``async def run`` is rejected before it is ever called, so no
    coroutine is created. A plain ``def`` that manufactures one is caught from
    its return value, and that coroutine is closed while still unstarted.
    """
    server = Server(socket_name=f"warnfree_{label}", engine=engine_factory())

    with pytest.raises(exc.AsyncEngineMismatch):
        server.cmd("list-sessions")

    gc.collect()

    assert [w for w in recwarn.list if issubclass(w.category, RuntimeWarning)] == []


class RecordingPopen(subprocess.Popen):  # type: ignore[type-arg]
    """A :class:`subprocess.Popen` that remembers every instance."""

    instances: t.ClassVar[list[RecordingPopen]] = []

    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        super().__init__(*args, **kwargs)
        RecordingPopen.instances.append(self)


def test_request_timeout_kills_and_reaps_the_client(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expiry kills the tmux client, collects it, and raises ``TmuxTimeout``."""
    server.new_session("slow")
    RecordingPopen.instances.clear()
    monkeypatch.setattr(subprocess, "Popen", RecordingPopen)
    engine = SubprocessEngine.for_server(server)
    request = CommandRequest.from_args("run-shell", "sleep 3", timeout=0.3)

    started = time.monotonic()
    with pytest.raises(exc.TmuxTimeout) as excinfo:
        engine.run(request)
    elapsed = time.monotonic() - started

    assert elapsed < 2.5
    assert excinfo.value.timeout == 0.3
    assert excinfo.value.cmd[-2:] == ["run-shell", "sleep 3"]
    assert isinstance(excinfo.value, exc.LibTmuxException)
    (client,) = RecordingPopen.instances
    assert client.returncode == -signal.SIGKILL
    with pytest.raises(ChildProcessError):
        os.waitpid(client.pid, os.WNOHANG)  # already reaped: no zombie left
    assert client.stdout is not None
    assert client.stdout.closed


def test_a_timeout_that_is_not_reached_changes_nothing(server: Server) -> None:
    """A generous timeout returns the normal result."""
    server.new_session("quick")
    engine = SubprocessEngine.for_server(server)

    result = engine.run(
        CommandRequest.from_args("display-message", "-p", "hi", timeout=30),
    )

    assert result.stdout == ("hi",)


@pytest.mark.parametrize(
    "payload",
    [
        b"plain text",
        bytes(range(256)),
        b"\xff\xfe not utf-8 \x00 nul",
        b"x" * 50_000,
    ],
    ids=["text", "all-bytes", "non-utf8", "50kb"],
)
def test_request_input_reaches_stdin_byte_exact(
    server: Server,
    tmp_path: pathlib.Path,
    payload: bytes,
) -> None:
    """``load-buffer -`` reads the payload unchanged, past tmux's 16 KiB limit."""
    server.new_session("stdin")
    engine = SubprocessEngine.for_server(server)
    saved = tmp_path / "buffer.bin"

    engine.run(
        CommandRequest.from_args("load-buffer", "-b", "inb", "-", input=payload),
    ).raise_for_status()
    engine.run(
        CommandRequest.from_args("save-buffer", "-b", "inb", str(saved)),
    ).raise_for_status()

    assert saved.read_bytes() == payload


def test_request_input_str_is_utf8_and_strict(server: Server) -> None:
    """Text is encoded as UTF-8; what cannot be encoded raises, never alters."""
    server.new_session("stdin_str")
    engine = SubprocessEngine.for_server(server)

    engine.run(
        CommandRequest.from_args("load-buffer", "-b", "ins", "-", input="café"),
    ).raise_for_status()
    shown = engine.run(CommandRequest.from_args("show-buffer", "-b", "ins"))
    with pytest.raises(UnicodeEncodeError):
        engine.run(CommandRequest.from_args("load-buffer", "-", input="\ud800"))

    assert shown.stdout == ("café",)


def test_request_input_stays_out_of_the_repr() -> None:
    """A payload may be large or secret; it is not printed."""
    request = CommandRequest.from_args("load-buffer", "-", input="s3cret")

    assert "s3cret" not in repr(request)


def test_cmd_forwards_timeout_and_input_at_every_level(session: Session) -> None:
    """``timeout`` and ``input`` reach the engine from each object's ``cmd``."""
    engine = CannedEngine()
    server = Server(socket_name="forwarding", engine=engine)
    # Built around the canned server so no tmux process is involved.
    window = type("W", (), {"window_id": "@1", "server": server})()
    pane = type("P", (), {"pane_id": "%1", "server": server})()
    sess = type("S", (), {"session_id": "$1", "server": server})()

    server.cmd("a", timeout=1.5, input=b"x")
    Session.cmd(sess, "b", timeout=2.5, input="y")
    Window.cmd(window, "c", timeout=3.5, input="z")
    Pane.cmd(pane, "d", timeout=4.5)

    assert [(r.args[0], r.timeout, r.input) for r in engine.requests] == [
        ("a", 1.5, b"x"),
        ("b", 2.5, "y"),
        ("c", 3.5, "z"),
        ("d", 4.5, None),
    ]


def test_server_cmd_timeout_end_to_end(server: Server) -> None:
    """``Server.cmd(timeout=)`` raises ``TmuxTimeout`` through the adapter."""
    server.new_session("e2e")

    with pytest.raises(exc.TmuxTimeout):
        server.cmd("run-shell", "sleep 3", timeout=0.3)


SEMICOLON_VALUES = ["a;b;", ";", "trailing;", "x;;", "two words;", r"end\;", "mid;dle"]


@pytest.mark.parametrize("value", SEMICOLON_VALUES, ids=range(len(SEMICOLON_VALUES)))
def test_trailing_semicolon_is_data_for_every_command(
    server: Server,
    value: str,
) -> None:
    """A data argument ending in ``;`` survives set-option, rename-window and formats.

    tmux's argv parser ends a command at an argument ending in ``;`` and drops
    the character, so the argv builder escapes each one. Three unrelated
    commands prove the fix is not specific to ``send-keys``/``set-buffer``.
    """
    session = server.new_session("semi")
    window = session.active_window

    server.cmd("set-option", "-g", "@semi", value)
    assert server.cmd("show-options", "-gqv", "@semi").stdout == [value]

    if "\\" not in value:  # tmux stores a window name vis-encoded
        window.cmd("rename-window", value)
        assert window.cmd("display-message", "-p", "#{window_name}").stdout == [value]

    assert server.cmd("display-message", "-p", f"fmt:{value}").stdout == [
        f"fmt:{value}",
    ]


def test_command_separator_still_chains_commands(server: Server) -> None:
    """A real separator splits the argv into two commands next to escaped data."""
    from libtmux.engines import CommandSeparator

    server.new_session("semi_chain")
    proc = server.cmd(
        "set-option",
        "-g",
        "@one",
        "1;",
        CommandSeparator(";"),
        "set-option",
        "-g",
        "@two",
        "2;",
    )
    assert proc.stderr == []
    assert server.cmd("show-options", "-gqv", "@one").stdout == ["1;"]
    assert server.cmd("show-options", "-gqv", "@two").stdout == ["2;"]


def test_engines_escape_data_semicolons_in_the_rendered_argv() -> None:
    r"""Subprocess and exec argv escape data ``;`` and keep a separator bare."""
    from libtmux.engines import CommandSeparator, ExecEngine

    request = CommandRequest.from_args(
        "display-message",
        "a;",
        CommandSeparator(";"),
        "list-windows",
    )
    for engine in (SubprocessEngine.of("tmux"), ExecEngine(tmux="tmux")):
        argv = engine.command_line(request)
        assert argv[-3:] == ("a\\;", ";", "list-windows")
