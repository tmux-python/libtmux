"""Tests for the native imsg engine (codec unit tests + live tmux parity).

The prototype this is ported from only ever tested against a fake socketpair
server; the live parity test here is the real wire-compatibility proof against a
tmux built from source, and it runs across the CI tmux matrix.
"""

from __future__ import annotations

import socket
import typing as t

import pytest

from libtmux.experimental.engines import (
    CommandRequest,
    ImsgEngine,
    SubprocessEngine,
    available_engines,
    create_engine,
)
from libtmux.experimental.engines.imsg.v8 import (
    IMSG_HEADER_SIZE,
    MessageType,
    ProtocolV8Codec,
)

if t.TYPE_CHECKING:
    from libtmux.session import Session

needs_af_unix = pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"),
    reason="imsg engine needs AF_UNIX sockets (POSIX only)",
)


@needs_af_unix
def test_imsg_connect_socket_failure_raises_oserror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A socket() failure surfaces as OSError, not UnboundLocalError."""
    import errno

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise OSError(errno.EMFILE, "too many open files")

    monkeypatch.setattr(
        "libtmux.experimental.engines.imsg.base.socket.socket",
        _boom,
    )
    with pytest.raises(OSError, match="too many open files"):
        ImsgEngine()._connect(socket_path="/nonexistent")


def test_imsg_registered() -> None:
    """The imsg engine is registered and constructible by name."""
    assert "imsg" in available_engines()
    assert type(create_engine("imsg")).__name__ == "ImsgEngine"


def test_v8_codec_header_round_trip() -> None:
    """A v8 frame packs to wire bytes and its header unpacks back (no tmux)."""
    codec = ProtocolV8Codec()
    payload = b"hello\x00"
    frame = codec.frame_message(200, payload, peer_id=8)
    wire = codec.pack_frame(frame)

    assert len(wire) == IMSG_HEADER_SIZE + len(payload)
    header = codec.unpack_header(wire[:IMSG_HEADER_SIZE])
    assert header.msg_type == 200
    assert header.peer_id == 8  # peer_id carries PROTOCOL_VERSION
    assert header.length == IMSG_HEADER_SIZE + len(payload)
    assert header.has_fd is False


def test_v8_command_message_packs_argc_and_argv() -> None:
    """A MSG_COMMAND frame encodes argc + NUL-joined argv (no tmux)."""
    codec = ProtocolV8Codec()
    frame = codec.command_message(("list-sessions", "-F", "#{session_id}"), peer_id=8)
    # int32 argc=3 then three NUL-terminated args
    assert frame.payload.startswith(b"\x03\x00\x00\x00")
    assert frame.payload.endswith(b"#{session_id}\x00")


class IdentifyFrameCase(t.NamedTuple):
    """One expected identify-burst frame count."""

    test_id: str
    msg_type: MessageType
    expected: int


IDENTIFY_FRAME_CASES = (
    IdentifyFrameCase("longflags-once", MessageType.MSG_IDENTIFY_LONGFLAGS, 1),
    IdentifyFrameCase("stdin-once", MessageType.MSG_IDENTIFY_STDIN, 1),
    IdentifyFrameCase("stdout-once", MessageType.MSG_IDENTIFY_STDOUT, 1),
    IdentifyFrameCase("done-once", MessageType.MSG_IDENTIFY_DONE, 1),
    IdentifyFrameCase("environ-one-per-var", MessageType.MSG_IDENTIFY_ENVIRON, 2),
)


@pytest.mark.parametrize(
    "case",
    IDENTIFY_FRAME_CASES,
    ids=[case.test_id for case in IDENTIFY_FRAME_CASES],
)
def test_identify_burst_frame_counts(case: IdentifyFrameCase) -> None:
    """The identify burst emits each message type the expected number of times.

    A real tmux client sends ``MSG_IDENTIFY_LONGFLAGS`` exactly once.
    """
    frames = ProtocolV8Codec().identify_messages(
        cwd="/tmp",
        term="xterm",
        tty_name="",
        client_pid=123,
        environ={"A": "1", "B": "2"},
    )
    count = sum(1 for frame in frames if frame.header.msg_type == int(case.msg_type))
    assert count == case.expected


def _socket_prefix(server: t.Any) -> tuple[str, ...]:
    """Build the -L/-S flag that targets the test server's socket."""
    if server.socket_name:
        return (f"-L{server.socket_name}",)
    return (f"-S{server.socket_path}",)


@needs_af_unix
def test_imsg_subprocess_parity(session: Session) -> None:
    """Imsg and subprocess engines return identical output for read commands.

    This is the wire-compatibility proof: the same typed CommandResult from
    speaking tmux's binary protocol directly and from forking the tmux CLI.
    """
    server = session.server
    prefix = _socket_prefix(server)
    session_id = session.session_id
    assert session_id is not None
    imsg = ImsgEngine()
    classic = SubprocessEngine()

    def parity(*cmd: str) -> None:
        request = CommandRequest.from_args(*prefix, *cmd)
        via_imsg = imsg.run(request)
        via_subprocess = classic.run(request)
        assert via_imsg.returncode == via_subprocess.returncode, cmd
        assert via_imsg.stdout == via_subprocess.stdout, cmd

    parity("display-message", "-p", "-t", session_id, "#{session_id}")
    parity("list-sessions", "-F", "#{session_id}")
    parity("has-session", "-t", session_id)
