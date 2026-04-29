"""Tests for libtmux engine resolution and protocol registry helpers."""

from __future__ import annotations

import contextlib
import os
import socket
import struct
import threading
import typing as t

import pytest
from typing_extensions import assert_type

from libtmux import common as libtmux_common, exc
from libtmux.common import resolve_engine, resolve_engine_spec
from libtmux.engines import (
    CommandRequest,
    CommandResult,
    EngineKind,
    EngineSpec,
    ImsgProtocolVersion,
    available_engines,
    available_imsg_protocol_versions,
    create_engine,
    create_imsg_protocol,
)
from libtmux.engines.control_mode import ControlModeEngine
from libtmux.engines.imsg import ImsgEngine
from libtmux.engines.imsg.base import _SelectorSocketTransport
from libtmux.engines.imsg.v8 import (
    IMSG_FD_MARK,
    IMSG_HEADER_SIZE,
    MessageType,
    ProtocolV8Codec,
    WriteDataMessage,
)
from libtmux.engines.subprocess import SubprocessEngine


class StaticEngine:
    """Small engine test double that records executed requests."""

    def __init__(self) -> None:
        self.requests: list[CommandRequest] = []

    def run(self, request: CommandRequest) -> CommandResult:
        """Record a command request and return a stable result."""
        self.requests.append(request)
        return CommandResult(
            cmd=["tmux", *request.args],
            stdout=["env-engine"],
            stderr=[],
            returncode=0,
            process=None,
        )


def test_engine_spec_subprocess_constructor() -> None:
    """Typed subprocess specs have no protocol version."""
    assert EngineSpec.subprocess() == EngineSpec(kind=EngineKind.SUBPROCESS)


def test_engine_spec_imsg_constructor() -> None:
    """Typed imsg specs preserve the requested protocol version."""
    assert EngineSpec.imsg(ImsgProtocolVersion.V8) == EngineSpec(
        kind=EngineKind.IMSG,
        protocol_version=8,
    )


def test_available_engines_lists_registered_backends() -> None:
    """The engine registry exposes the installed backend names."""
    assert available_engines() == ("control_mode", "imsg", "subprocess")


def test_create_subprocess_engine() -> None:
    """Named engine creation returns the subprocess backend."""
    engine = create_engine("subprocess")
    assert isinstance(engine, SubprocessEngine)


def test_create_imsg_engine_with_protocol_version() -> None:
    """Named engine creation returns the imsg backend with the requested version."""
    engine = create_engine("imsg", protocol_version="8")
    assert isinstance(engine, ImsgEngine)
    assert engine.protocol_version == "8"


def test_create_control_mode_engine_returns_engine() -> None:
    """Named engine creation returns a ``ControlModeEngine``."""
    engine = create_engine("control_mode")
    assert isinstance(engine, ControlModeEngine)


def test_run_batch_empty_returns_empty_list() -> None:
    """``run_batch([])`` is a no-op on every engine and returns ``[]``."""
    for engine in (SubprocessEngine(), ImsgEngine(protocol_version="8")):
        assert engine.run_batch([]) == []


def test_static_engine_run_batch_falls_back_to_loop() -> None:
    """Custom engines without an override get the trivial ``run_batch`` shape.

    A lightweight engine implementing only ``run`` and the trivial
    loop returns ``len(requests)`` results in send order. This is the
    semantic ``SubprocessEngine`` and ``ImsgEngine`` ship with.
    """

    class _LoopingEngine:
        def run(self, request: CommandRequest) -> CommandResult:
            return CommandResult(
                cmd=["tmux", *request.args],
                stdout=[" ".join(request.args)],
                stderr=[],
                returncode=0,
                process=None,
            )

        def run_batch(
            self,
            requests: t.Sequence[CommandRequest],
        ) -> list[CommandResult]:
            return [self.run(req) for req in requests]

    engine = _LoopingEngine()
    requests = [
        CommandRequest.from_args("display-message", "-p", "first"),
        CommandRequest.from_args("display-message", "-p", "second"),
        CommandRequest.from_args("display-message", "-p", "third"),
    ]
    results = engine.run_batch(requests)

    assert len(results) == 3
    assert [r.stdout[0].split()[-1] for r in results] == ["first", "second", "third"]


def test_control_mode_engine_run_rejects_empty_command() -> None:
    """``run()`` requires a tmux subcommand and refuses bare global flags."""
    engine = ControlModeEngine()
    with pytest.raises(exc.LibTmuxException, match="requires a tmux subcommand"):
        engine.run(CommandRequest(args=("-L", "missing")))


def test_engine_spec_control_mode_constructor() -> None:
    """Typed control-mode specs have no protocol version."""
    assert EngineSpec.control_mode() == EngineSpec(kind=EngineKind.CONTROL_MODE)


def test_engine_spec_control_mode_rejects_protocol_version() -> None:
    """Control mode is not parameterized by an imsg protocol version."""
    with pytest.raises(ValueError, match="only valid for the imsg engine"):
        EngineSpec(kind=EngineKind.CONTROL_MODE, protocol_version=8)


def test_libtmux_engine_env_selects_control_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``LIBTMUX_ENGINE=control_mode`` resolves to the control-mode engine."""
    monkeypatch.setattr(libtmux_common, "_default_engine", None)
    monkeypatch.setenv("LIBTMUX_ENGINE", "control_mode")

    assert resolve_engine_spec() == EngineSpec.control_mode()
    assert isinstance(resolve_engine(), ControlModeEngine)


def test_libtmux_engine_env_unknown_engine_message_lists_control_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The unknown-engine error mentions ``control_mode`` as a valid choice."""
    monkeypatch.setattr(libtmux_common, "_default_engine", None)
    monkeypatch.setenv("LIBTMUX_ENGINE", "bogus")

    with pytest.raises(exc.LibTmuxException, match="control_mode"):
        resolve_engine_spec()


def test_imsg_protocol_registry_defaults_to_latest() -> None:
    """The imsg protocol registry resolves to the highest registered version."""
    protocol = create_imsg_protocol()
    assert protocol.version == available_imsg_protocol_versions()[-1]


def test_imsg_protocol_registry_resolves_v8() -> None:
    """Protocol version 8 is available through the typed registry."""
    protocol = create_imsg_protocol("8")
    assert protocol.version == "8"


def test_resolve_engine_from_engine_spec() -> None:
    """Typed engine specs resolve to concrete backend instances."""
    engine = resolve_engine(EngineSpec.imsg(ImsgProtocolVersion.V8))
    assert isinstance(engine, ImsgEngine)
    assert engine.protocol_version == "8"


def test_resolve_engine_spec_from_engine_spec() -> None:
    """Typed engine specs round-trip through normalization unchanged."""
    spec = EngineSpec.imsg(ImsgProtocolVersion.V8)
    assert resolve_engine_spec(spec) == spec


def test_libtmux_engine_env_selects_default_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``LIBTMUX_ENGINE`` selects the runtime default engine."""
    monkeypatch.setattr(libtmux_common, "_default_engine", None)
    monkeypatch.setenv("LIBTMUX_ENGINE", " imsg ")

    assert resolve_engine_spec() == EngineSpec.imsg()
    assert isinstance(resolve_engine(), ImsgEngine)


def test_libtmux_engine_env_explicit_engine_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit engine arguments beat ``LIBTMUX_ENGINE``."""
    monkeypatch.setattr(libtmux_common, "_default_engine", None)
    monkeypatch.setenv("LIBTMUX_ENGINE", "imsg")

    assert resolve_engine_spec("subprocess") == EngineSpec.subprocess()
    assert isinstance(resolve_engine("subprocess"), SubprocessEngine)


def test_libtmux_engine_env_programmatic_default_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``set_default_engine`` overrides ``LIBTMUX_ENGINE``."""
    default_engine = SubprocessEngine()
    monkeypatch.setattr(libtmux_common, "_default_engine", None)
    monkeypatch.setenv("LIBTMUX_ENGINE", "imsg")
    libtmux_common.set_default_engine(default_engine)

    assert resolve_engine_spec() == EngineSpec.subprocess()
    assert resolve_engine() is default_engine


def test_libtmux_engine_env_rejects_unknown_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid ``LIBTMUX_ENGINE`` values fail clearly."""
    monkeypatch.setattr(libtmux_common, "_default_engine", None)
    monkeypatch.setenv("LIBTMUX_ENGINE", "bogus")

    with pytest.raises(exc.LibTmuxException, match="LIBTMUX_ENGINE"):
        resolve_engine_spec()


def test_tmux_cmd_from_request_uses_libtmux_engine_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prepared command execution uses the env-selected default engine."""
    fake_engine = StaticEngine()

    def create_fake_engine(
        name: str | EngineKind,
        *,
        protocol_version: str | int | ImsgProtocolVersion | None = None,
    ) -> StaticEngine:
        assert name == "imsg"
        assert protocol_version is None
        return fake_engine

    monkeypatch.setattr(libtmux_common, "_default_engine", None)
    monkeypatch.setenv("LIBTMUX_ENGINE", "imsg")
    monkeypatch.setattr(libtmux_common, "create_engine", create_fake_engine)

    result = libtmux_common.tmux_cmd.from_request(
        CommandRequest(args=("display-message", "hello")),
    )

    assert result.stdout == ["env-engine"]
    assert fake_engine.requests == [
        CommandRequest(args=("display-message", "hello")),
    ]


def test_resolve_engine_string_overloads() -> None:
    """Literal engine names resolve to concrete backend types."""
    assert_type(resolve_engine("subprocess"), SubprocessEngine)
    assert_type(resolve_engine("imsg"), ImsgEngine)
    assert_type(
        resolve_engine("imsg", protocol_version=ImsgProtocolVersion.V8),
        ImsgEngine,
    )


def test_resolve_engine_spec_string_overloads() -> None:
    """String-based engine specs stay type-checker friendly."""
    assert_type(resolve_engine_spec("subprocess"), EngineSpec)
    assert_type(resolve_engine_spec("imsg"), EngineSpec)
    assert_type(
        resolve_engine_spec("imsg", protocol_version=ImsgProtocolVersion.V8),
        EngineSpec,
    )


def test_resolve_engine_spec_requires_explicit_imsg_for_protocol_hint() -> None:
    """Protocol hints require the public imsg selection."""
    with pytest.raises(ValueError, match="explicit imsg"):
        resolve_engine_spec(protocol_version="8")  # type: ignore[call-overload]


def test_resolve_engine_spec_rejects_protocol_hint_for_subprocess() -> None:
    """Only the imsg engine accepts protocol hints."""
    with pytest.raises(ValueError, match="only valid for the imsg engine"):
        resolve_engine_spec(  # type: ignore[call-overload]
            "subprocess",
            protocol_version="8",
        )


def test_resolve_engine_spec_rejects_protocol_hint_for_engine_instance() -> None:
    """Concrete engine instances already encode their protocol semantics."""
    with pytest.raises(ValueError, match="concrete engine instance"):
        resolve_engine_spec(  # type: ignore[call-overload]
            SubprocessEngine(),
            protocol_version="8",
        )


def test_protocol_v8_identify_order_includes_stdio_fds() -> None:
    """Protocol v8 identify frames match tmux client ordering."""
    codec = ProtocolV8Codec()
    stdin_read, stdin_write = os.pipe()
    stdout_read, stdout_write = os.pipe()
    try:
        frames = codec.identify_messages(
            cwd="/tmp",
            term="tmux-256color",
            tty_name="/dev/pts/99",
            client_pid=123,
            environ={"A": "B"},
            flags=7,
            features=9,
            stdin_fd=stdin_read,
            stdout_fd=stdout_write,
        )
        assert [frame.header.msg_type for frame in frames[:9]] == [
            int(MessageType.MSG_IDENTIFY_LONGFLAGS),
            int(MessageType.MSG_IDENTIFY_LONGFLAGS),
            int(MessageType.MSG_IDENTIFY_TERM),
            int(MessageType.MSG_IDENTIFY_FEATURES),
            int(MessageType.MSG_IDENTIFY_TTYNAME),
            int(MessageType.MSG_IDENTIFY_CWD),
            int(MessageType.MSG_IDENTIFY_STDIN),
            int(MessageType.MSG_IDENTIFY_STDOUT),
            int(MessageType.MSG_IDENTIFY_CLIENTPID),
        ]
        assert frames[6].fd == stdin_read
        assert frames[6].header.has_fd
        assert frames[7].fd == stdout_write
        assert frames[7].header.has_fd
        assert frames[-1].header.msg_type == int(MessageType.MSG_IDENTIFY_DONE)
    finally:
        for fd in (stdin_read, stdin_write, stdout_read, stdout_write):
            with contextlib.suppress(OSError):
                os.close(fd)


def test_protocol_v8_header_fd_marker_decodes_cleanly() -> None:
    """The v8 codec preserves the imsg FD marker outside the length."""
    codec = ProtocolV8Codec()
    raw_header = struct.pack(
        "=IIII",
        int(MessageType.MSG_IDENTIFY_STDIN),
        IMSG_HEADER_SIZE | IMSG_FD_MARK,
        8,
        99,
    )

    header = codec.unpack_header(raw_header)

    assert header.length == IMSG_HEADER_SIZE
    assert header.has_fd
    assert header.peer_id == 8
    assert header.pid == 99


def test_protocol_v8_rejects_invalid_header_length() -> None:
    """The v8 codec rejects malformed imsg frame lengths."""
    codec = ProtocolV8Codec()
    raw_header = struct.pack(
        "=IIII",
        int(MessageType.MSG_READY),
        IMSG_HEADER_SIZE - 1,
        8,
        0,
    )

    with pytest.raises(exc.TmuxProtocolError, match="Invalid tmux imsg length"):
        codec.unpack_header(raw_header)


def test_protocol_v8_parses_write_payload() -> None:
    """The v8 codec returns typed payload objects for known message types."""
    codec = ProtocolV8Codec()
    payload = struct.pack("=i", 3) + b"hello"

    message = codec.parse_message(
        int(MessageType.MSG_WRITE),
        payload,
        peer_id=8,
        pid=0,
    )

    assert message == WriteDataMessage(stream=3, data=b"hello")


def test_selector_transport_receives_partial_frame() -> None:
    """The selector transport reassembles frames split across socket reads."""
    codec = ProtocolV8Codec()
    left, right = socket.socketpair()
    transport = _SelectorSocketTransport(left)
    frame = codec.frame_message(
        MessageType.MSG_WRITE,
        struct.pack("=i", 1) + b"partial",
        peer_id=8,
    )
    packed = codec.pack_frame(frame)

    def send_chunks() -> None:
        right.sendall(packed[:5])
        right.sendall(packed[5:])

    sender = threading.Thread(target=send_chunks)
    sender.start()
    try:
        received = transport.recv_frame(codec)
    finally:
        sender.join()
        transport.close()
        left.close()
        right.close()

    assert received.header.msg_type == int(MessageType.MSG_WRITE)
    assert received.payload == frame.payload


def test_selector_transport_sends_and_receives_fd() -> None:
    """The selector transport passes one descriptor with an imsg frame."""
    codec = ProtocolV8Codec()
    left, right = socket.socketpair()
    read_transport = _SelectorSocketTransport(left)
    write_transport = _SelectorSocketTransport(right)
    read_fd, write_fd = os.pipe()
    received_fd: int | None = None

    try:
        frame = codec.frame_message(
            MessageType.MSG_IDENTIFY_STDIN,
            b"",
            peer_id=8,
            fd=write_fd,
        )
        write_fd = -1
        write_transport.send_frame(codec, frame)
        received = read_transport.recv_frame(codec)
        received_fd = received.fd

        assert received.header.msg_type == int(MessageType.MSG_IDENTIFY_STDIN)
        assert received.header.has_fd
        assert received_fd is not None
    finally:
        if received_fd is not None:
            os.close(received_fd)
        if write_fd != -1:
            os.close(write_fd)
        os.close(read_fd)
        read_transport.close()
        write_transport.close()
        left.close()
        right.close()


def test_imsg_socket_command_sends_fd_backed_identify_burst() -> None:
    """The imsg engine sends a tmux-shaped identify burst before commands."""
    codec = ProtocolV8Codec()
    client_sock, server_sock = socket.socketpair()
    engine = ImsgEngine(protocol_version="8")
    received_types: list[int] = []
    received_fd_types: list[int] = []
    server_errors: list[BaseException] = []

    def fake_server() -> None:
        transport = _SelectorSocketTransport(server_sock)
        try:
            while True:
                frame = transport.recv_frame(codec)
                received_types.append(frame.header.msg_type)
                if frame.fd is not None:
                    received_fd_types.append(frame.header.msg_type)
                    os.close(frame.fd)
                if frame.header.msg_type == int(MessageType.MSG_COMMAND):
                    break

            transport.send_frame(
                codec,
                codec.frame_message(
                    MessageType.MSG_WRITE_OPEN,
                    struct.pack("=iii", 1, -1, 0) + b"\0",
                    peer_id=8,
                ),
            )
            transport.send_frame(
                codec,
                codec.frame_message(
                    MessageType.MSG_WRITE,
                    struct.pack("=i", 1) + b"hello\n",
                    peer_id=8,
                ),
            )
            transport.send_frame(
                codec,
                codec.frame_message(
                    MessageType.MSG_WRITE_CLOSE,
                    struct.pack("=i", 1),
                    peer_id=8,
                ),
            )
            transport.send_frame(
                codec,
                codec.frame_message(
                    MessageType.MSG_EXIT,
                    struct.pack("=i", 0),
                    peer_id=8,
                ),
            )
            transport.send_frame(
                codec,
                codec.frame_message(MessageType.MSG_EXITED, b"", peer_id=8),
            )
        except BaseException as error:
            server_errors.append(error)
        finally:
            transport.close()

    server = threading.Thread(target=fake_server)
    server.start()
    try:
        result = engine._run_socket_command(
            sock=client_sock,
            codec=codec,
            peer_id=8,
            command_argv=("display-message", "-p", "hello"),
            cmd=["tmux", "display-message", "-p", "hello"],
        )
    finally:
        client_sock.close()
        server_sock.close()
        server.join()

    assert not server_errors
    assert result.stdout == ["hello"]
    assert received_types[:9] == [
        int(MessageType.MSG_IDENTIFY_LONGFLAGS),
        int(MessageType.MSG_IDENTIFY_LONGFLAGS),
        int(MessageType.MSG_IDENTIFY_TERM),
        int(MessageType.MSG_IDENTIFY_FEATURES),
        int(MessageType.MSG_IDENTIFY_TTYNAME),
        int(MessageType.MSG_IDENTIFY_CWD),
        int(MessageType.MSG_IDENTIFY_STDIN),
        int(MessageType.MSG_IDENTIFY_STDOUT),
        int(MessageType.MSG_IDENTIFY_CLIENTPID),
    ]
    assert received_types[-1] == int(MessageType.MSG_COMMAND)
    assert received_fd_types == [
        int(MessageType.MSG_IDENTIFY_STDIN),
        int(MessageType.MSG_IDENTIFY_STDOUT),
    ]


def test_imsg_engine_run_translates_broken_pipe_to_no_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A server that dies between connect() and the first send yields ``returncode=1``.

    Regression: tmuxp tests that kill the last session (and therefore the
    tmux server) and then call ``server.has_session(...)`` would propagate
    ``BrokenPipeError`` from the imsg transport. The engine now translates
    EPIPE on the first I/O into the same "no server running" ``CommandResult``
    that the connect-time ``_NoServerError`` path produces.
    """
    client_sock, server_sock = socket.socketpair()
    server_sock.shutdown(socket.SHUT_RDWR)
    server_sock.close()

    engine = ImsgEngine(protocol_version="8")

    def fake_connect(*, socket_path: str) -> socket.socket:
        del socket_path
        return client_sock

    monkeypatch.setattr(engine, "_connect", fake_connect)

    try:
        result = engine.run(
            CommandRequest.from_args(
                "-L",
                "test-no-server",
                "has-session",
                "-t=foo",
            ),
        )
    finally:
        with contextlib.suppress(OSError):
            client_sock.close()

    assert result.returncode == 1
    assert result.stdout == []
    assert result.stderr
    assert "no server running" in result.stderr[0]


def _counting_which(
    monkeypatch: pytest.MonkeyPatch,
    module_path: str,
) -> t.Callable[[], int]:
    """Patch ``shutil.which`` in *module_path* and return a call counter.

    The shared helper keeps the assertion symmetric across both engine
    backends without duplicating monkeypatch glue.
    """
    import shutil as _shutil

    counter = 0
    real_which = _shutil.which

    def _which(name: str, *args: t.Any, **kwargs: t.Any) -> str | None:
        nonlocal counter
        if name == "tmux":
            counter += 1
        return real_which(name, *args, **kwargs)

    monkeypatch.setattr(f"{module_path}.shutil.which", _which)
    return lambda: counter


def test_subprocess_engine_caches_default_tmux_bin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SubprocessEngine`` resolves ``shutil.which("tmux")`` once per instance.

    ``shutil.which`` does a $PATH walk on every call. The engine hits its
    fallback resolver on the hot path, so caching it eliminates redundant
    syscalls without changing the override semantics for explicit
    ``request.tmux_bin`` or ``self.tmux_bin``.
    """
    count = _counting_which(monkeypatch, "libtmux.engines.subprocess")

    engine = SubprocessEngine()
    first = engine._resolve_default_tmux_bin()
    second = engine._resolve_default_tmux_bin()
    third = engine._resolve_default_tmux_bin()

    assert first == second == third
    assert count() == 1, f"expected 1 shutil.which lookup, got {count()}"


def test_imsg_engine_caches_default_tmux_bin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ImsgEngine`` resolves ``shutil.which("tmux")`` once per instance."""
    count = _counting_which(monkeypatch, "libtmux.engines.imsg.base")

    engine = ImsgEngine(protocol_version="8")
    first = engine._resolve_tmux_bin()
    second = engine._resolve_tmux_bin()
    third = engine._resolve_tmux_bin()

    assert first == second == third
    assert count() == 1, f"expected 1 shutil.which lookup, got {count()}"


def test_control_mode_engine_caches_default_tmux_bin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ControlModeEngine`` resolves ``shutil.which("tmux")`` once per instance."""
    count = _counting_which(monkeypatch, "libtmux.engines.control_mode.base")

    engine = ControlModeEngine()
    first = engine._resolve_default_tmux_bin()
    second = engine._resolve_default_tmux_bin()
    third = engine._resolve_default_tmux_bin()

    assert first == second == third
    assert count() == 1, f"expected 1 shutil.which lookup, got {count()}"
