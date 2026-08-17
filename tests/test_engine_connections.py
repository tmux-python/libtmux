"""Tests for engine connection inspection, constraints, and safe rebinding."""

from __future__ import annotations

import collections.abc
import shutil
import typing as t

import pytest

from libtmux import exc
from libtmux.engines import (
    CommandRequest,
    CommandResult,
    HasConnection,
    ServerConnection,
    SubprocessEngine,
    SupportsConnection,
)
from libtmux.experimental.engines import (
    AsyncControlModeEngine,
    AsyncSubprocessEngine,
    ControlModeEngine,
    SubprocessEngine as ExperimentalSubprocessEngine,
)
from libtmux.server import Server
from libtmux.session import Session

SyncSubprocessType = type[SubprocessEngine] | type[ExperimentalSubprocessEngine]
SyncSubprocess = SubprocessEngine | ExperimentalSubprocessEngine


def _subprocess_engine(
    engine_type: SyncSubprocessType,
    *,
    tmux_bin: str | None = None,
    server_args: collections.abc.Sequence[str] = (),
) -> SyncSubprocess:
    """Build either synchronous stateless subprocess engine."""
    if engine_type is SubprocessEngine:
        return SubprocessEngine.of(tmux_bin=tmux_bin, server_args=server_args)
    return ExperimentalSubprocessEngine(
        tmux_bin=tmux_bin,
        server_args=server_args,
    )


@pytest.mark.parametrize(
    "engine",
    [
        SubprocessEngine(),
        ExperimentalSubprocessEngine(),
        AsyncSubprocessEngine(),
    ],
    ids=["core", "experimental-sync", "experimental-async"],
)
def test_stateless_subprocess_engines_are_inspectable_and_rebindable(
    engine: object,
) -> None:
    """Stateless subprocess engines opt into both connection capabilities."""
    target = ServerConnection.of("/target/tmux", ("-Ltarget",))

    assert isinstance(engine, HasConnection)
    assert isinstance(engine, SupportsConnection)
    rebound = engine.with_connection(target)
    assert rebound is not engine
    assert rebound.connection == target


@pytest.mark.parametrize(
    "engine",
    [ControlModeEngine(), AsyncControlModeEngine()],
    ids=["sync", "async"],
)
def test_control_engines_are_inspectable_but_pinned(engine: object) -> None:
    """Persistent controls report their connection but cannot be cloned safely."""
    assert isinstance(engine, HasConnection)
    assert not isinstance(engine, SupportsConnection)


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ((), False),
        (("-2",), False),
        (("-8",), False),
        (("-f/dev/null",), False),
        (("-f", "/dev/null"), False),
        (("-q",), False),
        (("-2q", "-f/dev/null"), False),
        (("-Lwork",), True),
        (("-L", "work"), True),
        (("-S/tmp/work.sock",), True),
        (("-S", "/tmp/work.sock"), True),
    ],
)
def test_names_server_only_recognizes_effective_socket_selectors(
    args: tuple[str, ...],
    expected: bool,
) -> None:
    """Color, config, and quiet globals do not select a tmux server."""
    assert ServerConnection.of(args=args).names_server is expected


@pytest.mark.parametrize(
    "engine_type",
    [SubprocessEngine, ExperimentalSubprocessEngine],
    ids=["core", "experimental"],
)
def test_missing_server_constraints_merge_into_stateless_engine(
    engine_type: SyncSubprocessType,
) -> None:
    """A safe rebind overlays only constraints absent from the engine."""
    original = _subprocess_engine(
        engine_type,
        tmux_bin="/engine/tmux",
        server_args=("-q", "-Lengine"),
    )
    server = Server(
        config_file="/server/tmux.conf",
        colors=256,
        engine=t.cast("t.Any", original),
    )

    rebound = server.engine

    assert rebound is not original
    assert isinstance(rebound, HasConnection)
    assert rebound.connection == ServerConnection.of(
        "/engine/tmux",
        ("-q", "-Lengine", "-2", "-f/server/tmux.conf"),
    )
    assert original.connection == ServerConnection.of(
        "/engine/tmux",
        ("-q", "-Lengine"),
    )


@pytest.mark.parametrize(
    "engine_type",
    [SubprocessEngine, ExperimentalSubprocessEngine],
    ids=["core", "experimental"],
)
def test_server_socket_and_binary_fill_engine_gaps(
    engine_type: SyncSubprocessType,
) -> None:
    """Explicit Server socket and binary values bind an otherwise bare engine."""
    original = _subprocess_engine(engine_type, server_args=("-f/engine.conf",))
    server = Server(
        socket_name="server",
        tmux_bin="/server/tmux",
        engine=t.cast("t.Any", original),
    )

    rebound = server.engine

    assert isinstance(rebound, HasConnection)
    assert rebound.connection == ServerConnection.of(
        "/server/tmux",
        ("-f/engine.conf", "-Lserver"),
    )


@pytest.mark.parametrize(
    "engine_type",
    [SubprocessEngine, ExperimentalSubprocessEngine],
    ids=["core", "experimental"],
)
def test_matching_normalized_constraints_preserve_engine_instance(
    engine_type: SyncSubprocessType,
) -> None:
    """Equivalent attached and separate globals do not force a clone."""
    engine = _subprocess_engine(
        engine_type,
        tmux_bin="/same/tmux",
        server_args=("-2", "-f", "/same.conf", "-L", "same"),
    )
    server = Server(
        socket_name="same",
        config_file="/same.conf",
        colors=256,
        tmux_bin="/same/tmux",
        engine=t.cast("t.Any", engine),
    )

    assert server.engine is engine


def test_socket_path_is_the_effective_selector_when_socket_name_is_also_present() -> (
    None
):
    """Tmux ignores ``-L`` whenever ``-S`` is present."""
    engine = SubprocessEngine.of(
        server_args=("-Lignored", "-S", "/tmp/effective.sock"),
    )
    server = Server(socket_path="/tmp/effective.sock", engine=engine)

    assert server.engine is engine


def test_repeated_config_files_do_not_collapse_to_the_final_value() -> None:
    """Extra ``-f`` inputs remain a semantic conflict, even if the last matches."""
    engine = SubprocessEngine.of(server_args=("-f/extra.conf", "-f/required.conf"))
    server = Server(config_file="/required.conf", engine=engine)

    with pytest.raises(exc.EngineConfigurationMismatch, match="config"):
        _ = server.engine


@pytest.mark.parametrize(
    ("server_kwargs", "engine_bin", "engine_args", "field"),
    [
        ({"socket_name": "server"}, None, ("-Lengine",), "socket"),
        ({"socket_path": "/server.sock"}, None, ("-S/engine.sock",), "socket"),
        ({"config_file": "/server.conf"}, None, ("-f/engine.conf",), "config"),
        ({"colors": 256}, None, ("-8",), "color"),
        ({"tmux_bin": "/server/tmux"}, "/engine/tmux", (), "binary"),
    ],
)
@pytest.mark.parametrize(
    "engine_type",
    [SubprocessEngine, ExperimentalSubprocessEngine],
    ids=["core", "experimental"],
)
def test_explicit_server_constraint_conflicts_raise_before_dispatch(
    server_kwargs: dict[str, t.Any],
    engine_bin: str | None,
    engine_args: tuple[str, ...],
    field: str,
    engine_type: SyncSubprocessType,
) -> None:
    """Contradictory explicit values raise a named configuration error."""
    engine = _subprocess_engine(
        engine_type,
        tmux_bin=engine_bin,
        server_args=engine_args,
    )

    server = Server(engine=t.cast("t.Any", engine), **server_kwargs)

    with pytest.raises(exc.EngineConfigurationMismatch, match=field):
        _ = server.engine


@pytest.mark.parametrize(
    "engine",
    [
        ControlModeEngine(server_args=("-Lsame",)),
        AsyncControlModeEngine(server_args=("-Lsame",)),
    ],
    ids=["sync", "async"],
)
def test_matching_pinned_control_connection_preserves_instance(engine: object) -> None:
    """A pinned control already satisfying Server constraints is reused."""
    server = Server(socket_name="same", engine=t.cast("t.Any", engine))

    assert server.engine is engine


@pytest.mark.parametrize(
    "engine",
    [
        ControlModeEngine(server_args=("-Lsame",)),
        AsyncControlModeEngine(server_args=("-Lsame",)),
    ],
    ids=["sync", "async"],
)
def test_pinned_controls_are_not_cloned_to_fill_missing_constraints(
    engine: object,
) -> None:
    """A live-capable control cannot be auto-cloned to add configuration."""
    server = Server(
        socket_name="same",
        config_file="/required.conf",
        engine=t.cast("t.Any", engine),
    )

    with pytest.raises(exc.EngineConfigurationMismatch, match="rebind"):
        _ = server.engine

    assert t.cast("t.Any", engine)._proc is None


class _ConnectionlessEngine:
    """Minimal fake with no tmux connection capability."""

    def run(self, request: CommandRequest) -> CommandResult:
        """Return a canned success without touching tmux."""
        return CommandResult(cmd=("fake", *request.args))

    def run_batch(
        self,
        requests: collections.abc.Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Return one canned success per request."""
        return [self.run(request) for request in requests]


def test_scoped_server_preserves_connectionless_fake() -> None:
    """Server constraints do not invent connection behavior for a fake."""
    engine = _ConnectionlessEngine()
    server = Server(
        socket_name="scoped",
        config_file="/required.conf",
        colors=256,
        tmux_bin="/required/tmux",
        engine=engine,
    )

    assert server.engine is engine


@pytest.mark.parametrize(
    "engine_type",
    [SubprocessEngine, ExperimentalSubprocessEngine],
    ids=["core", "experimental"],
)
def test_unscoped_server_preserves_engine(engine_type: SyncSubprocessType) -> None:
    """A Server with no explicit constraints never rewrites an engine."""
    engine = _subprocess_engine(
        engine_type,
        tmux_bin="/engine/tmux",
        server_args=("-2", "-f/engine.conf", "-Lengine"),
    )

    assert Server(engine=t.cast("t.Any", engine)).engine is engine


@pytest.mark.parametrize(
    "engine_type",
    [SubprocessEngine, ExperimentalSubprocessEngine],
    ids=["core", "experimental"],
)
def test_server_mutation_reconciles_again_at_dispatch_time(
    engine_type: SyncSubprocessType,
) -> None:
    """Every public connection mutation invalidates an adopted engine."""
    engine = _subprocess_engine(engine_type)
    server = Server(socket_name="first", engine=t.cast("t.Any", engine))

    first = server.engine
    server.socket_name = "second"
    second = server.engine
    server.socket_name = None

    assert isinstance(first, HasConnection)
    assert isinstance(second, HasConnection)
    assert first.connection.args == ("-Lfirst",)
    assert second.connection.args == ("-Lsecond",)
    assert first is not second
    assert server.engine is engine


def test_rebind_cache_is_scoped_to_the_injected_engine_identity() -> None:
    """Replacing ``_engine`` cannot return a prior engine's cached clone."""
    first_source = SubprocessEngine()
    second_source = SubprocessEngine()
    server = Server(socket_name="identity_cache", engine=first_source)

    first = server.engine
    server._engine = second_source
    second = server.engine

    assert first is not second
    assert isinstance(second, HasConnection)
    assert second.connection.args == ("-Lidentity_cache",)


class _LyingRebindEngine:
    """Safe-rebind double that returns an engine on the wrong connection."""

    def __init__(self) -> None:
        self.connection = ServerConnection()
        self.runs = 0

    def with_connection(self, connection: ServerConnection) -> _LyingRebindEngine:
        """Ignore the requested connection and return this unbound engine."""
        return self

    def run(self, request: CommandRequest) -> CommandResult:
        """Record a dispatch that connection verification must prevent."""
        self.runs += 1
        return CommandResult(cmd=("liar", *request.args))

    def run_batch(
        self,
        requests: collections.abc.Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Run each request through the lying engine."""
        return [self.run(request) for request in requests]


def test_server_verifies_rebound_engine_reports_requested_connection() -> None:
    """A broken ``with_connection`` result is rejected before ``run``."""
    engine = _LyingRebindEngine()
    server = Server(socket_name="required", engine=engine)

    with pytest.raises(exc.EngineConfigurationMismatch, match="reported"):
        server.cmd("list-sessions")

    assert engine.runs == 0


@pytest.mark.parametrize(
    "attr",
    ["sessions", "windows", "panes", "clients", "attached_sessions"],
)
def test_lenient_list_accessors_propagate_configuration_mismatch(attr: str) -> None:
    """A broken engine configuration is not reported as an empty listing."""
    engine = SubprocessEngine.of(server_args=("-Lengine",))
    server = Server(socket_name="server", engine=engine)

    with pytest.raises(exc.EngineConfigurationMismatch):
        getattr(server, attr)


def test_list_accessor_reconciles_binary_before_version_probe() -> None:
    """A binary conflict surfaces before a list query tries either binary."""
    engine = SubprocessEngine.of(tmux_bin="/engine/tmux")
    server = Server(tmux_bin="/server/tmux", engine=engine)

    with pytest.raises(exc.EngineConfigurationMismatch, match="binary"):
        _ = server.sessions


def test_liveness_probe_propagates_configuration_mismatch() -> None:
    """Invalid engine wiring is not translated to a dead tmux server."""
    engine = ControlModeEngine(server_args=("-Lelsewhere",))
    server = Server(socket_name="required", engine=engine)

    with pytest.raises(exc.EngineConfigurationMismatch):
        server.is_alive()

    assert engine._proc is None


class _VersionedListingEngine(_ConnectionlessEngine):
    """Connectionless listing fake with an authoritative tmux version."""

    def __init__(self) -> None:
        self.version_calls = 0

    def tmux_version(self) -> str:
        """Return a version without consulting ``Server.tmux_bin``."""
        self.version_calls += 1
        return "3.2a"


def test_list_format_version_comes_from_the_selected_engine() -> None:
    """Object queries probe the injected transport's binary, not Server's."""
    engine = _VersionedListingEngine()
    server = Server(tmux_bin="/definitely/not/tmux", engine=engine)

    assert server.sessions == []
    assert engine.version_calls == 1


def test_control_server_mutation_is_rejected_after_start(session: Session) -> None:
    """A live control connection stays pinned when its Server scope mutates."""
    source = session.server
    engine = ControlModeEngine.for_server(source)
    proxy = Server(socket_name=source.socket_name, engine=engine)

    with engine:
        result = proxy.cmd("display-message", "-p", "before-mutation")
        process = engine._proc
        assert result.stdout == ["before-mutation"]
        assert process is not None

        proxy.socket_name = f"{source.socket_name}_mutated"
        with pytest.raises(exc.EngineConfigurationMismatch):
            proxy.cmd("display-message", "-p", "after-mutation")

        assert engine._proc is process
        assert process.poll() is None


def test_live_two_socket_control_mismatch_has_no_side_effect(
    session: Session,
    TestServer: t.Callable[..., Server],
) -> None:
    """A mismatched pinned dispatch changes neither live tmux server."""
    source = session.server
    destination = TestServer()
    destination.new_session(session_name="destination")
    marker = f"mismatch_{destination.socket_name}"

    with ControlModeEngine.for_server(source) as engine:
        assert engine.run(CommandRequest.from_args("list-sessions")).returncode == 0
        proxy = Server(socket_name=destination.socket_name, engine=engine)
        with pytest.raises(exc.EngineConfigurationMismatch):
            proxy.cmd("new-session", "-d", "-s", marker)

    assert not source.has_session(marker)
    assert not destination.has_session(marker)


@pytest.mark.parametrize(
    "engine_type",
    [SubprocessEngine, ExperimentalSubprocessEngine],
    ids=["core", "experimental"],
)
def test_live_rebind_with_custom_binary_targets_required_socket(
    TestServer: type[Server],
    engine_type: SyncSubprocessType,
) -> None:
    """A binary-only engine adopts the right socket among two live servers."""
    left = TestServer()
    right = TestServer()
    left.new_session(session_name="left")
    right.new_session(session_name="right")
    tmux_bin = shutil.which("tmux")
    assert tmux_bin is not None
    engine = _subprocess_engine(engine_type, tmux_bin=tmux_bin)
    server = Server(socket_name=right.socket_name, engine=t.cast("t.Any", engine))

    result = server.cmd("list-sessions", "-F#{session_name}")

    assert result.stdout == ["right"]


@pytest.mark.parametrize(
    "engine_type",
    [SubprocessEngine, ExperimentalSubprocessEngine],
    ids=["core", "experimental"],
)
def test_live_config_only_server_preserves_engine_socket(
    TestServer: type[Server],
    engine_type: SyncSubprocessType,
) -> None:
    """A config-only Server merges onto an engine pinned to one of two sockets."""
    left = TestServer()
    right = TestServer()
    left.new_session(session_name="left")
    right.new_session(session_name="right")
    engine = _subprocess_engine(
        engine_type,
        server_args=(f"-L{right.socket_name}",),
    )
    server = Server(config_file="/dev/null", engine=t.cast("t.Any", engine))

    result = server.cmd("list-sessions", "-F#{session_name}")

    assert result.stdout == ["right"]
