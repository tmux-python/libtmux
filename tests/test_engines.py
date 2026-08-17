"""Tests for :mod:`libtmux.engines`, the tmux command execution seam."""

from __future__ import annotations

import asyncio
import gc
import logging
import subprocess
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
from libtmux.server import Server

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

    with pytest.raises(exc.LibTmuxException):
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
    with pytest.raises(exc.LibTmuxException):
        _ = proc.process


def test_process_is_popen_under_default_engine(session: Session) -> None:
    """``.process`` reads exactly as it did before the seam existed."""
    proc = session.server.cmd("display-message", "-p", "hi")

    assert isinstance(proc.process, subprocess.Popen)
    assert proc.process.returncode == 0


def test_core_subprocess_command_line_encodes_only_command_data() -> None:
    r"""Core protects suffixes without rewriting connection option values."""
    engine = SubprocessEngine.of("tmux", ("-Lsocket;",))

    command_line = engine.command_line(
        CommandRequest.from_args("display-message", "literal;", r"escaped\;"),
    )

    assert command_line == (
        "tmux",
        "-Lsocket;",
        "display-message",
        r"literal\;",
        r"escaped\;",
    )


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
        "-Lbin_only_adopts",
        "list-sessions",
    )


def test_explicit_server_binary_conflicts_with_engine_binary() -> None:
    """Two explicit binary values cannot be reconciled silently."""
    engine = SubprocessEngine.of(tmux_bin="/nonexistent/tmux")
    server = Server(socket_name="bin_kept", tmux_bin="/other/tmux", engine=engine)

    with pytest.raises(exc.EngineConfigurationMismatch, match="binary"):
        _ = server.engine


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


def test_engine_and_server_socket_conflict_is_explicit() -> None:
    """Contradictory socket authorities raise before a command runs."""
    engine = SubprocessEngine.of(server_args=("-Lelsewhere",))
    server = Server(socket_name="not_elsewhere", engine=engine)

    with pytest.raises(exc.EngineConfigurationMismatch, match="socket"):
        _ = server.engine


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


@pytest.mark.parametrize("colors", (16, 88))
def test_unknown_color_raises_on_every_path(colors: int) -> None:
    """An unknown ``colors`` value raises, matching ``Server.cmd``'s contract."""
    server = Server(socket_name="bad_colors")
    server.colors = colors

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
