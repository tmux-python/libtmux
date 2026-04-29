"""tmux imsg protocol version 8."""

from __future__ import annotations

import dataclasses
import enum
import struct
import typing as t

from libtmux import exc
from libtmux.engines.imsg.types import ImsgFrame, ImsgHeader
from libtmux.engines.registry import register_imsg_protocol

IMSG_HEADER_SIZE = 16
MAX_IMSGSIZE = 16384
IMSG_FD_MARK = 0x80000000

_HEADER = struct.Struct("=IIII")
_INT32 = struct.Struct("=i")
_UINT64 = struct.Struct("=Q")
_WRITE_OPEN = struct.Struct("=iii")
_WRITE_DATA = struct.Struct("=i")
_WRITE_READY = struct.Struct("=ii")
_WRITE_CLOSE = struct.Struct("=i")
_READ_OPEN = struct.Struct("=ii")
_READ_DONE = struct.Struct("=ii")
_ExitStatus = tuple[int, str | None]


class MessageType(enum.IntEnum):
    """Known tmux protocol v8 message types from ``tmux-protocol.h``."""

    MSG_VERSION = 12
    MSG_IDENTIFY_FLAGS = 100
    MSG_IDENTIFY_TERM = 101
    MSG_IDENTIFY_TTYNAME = 102
    MSG_IDENTIFY_OLDCWD = 103
    MSG_IDENTIFY_STDIN = 104
    MSG_IDENTIFY_ENVIRON = 105
    MSG_IDENTIFY_DONE = 106
    MSG_IDENTIFY_CLIENTPID = 107
    MSG_IDENTIFY_CWD = 108
    MSG_IDENTIFY_FEATURES = 109
    MSG_IDENTIFY_STDOUT = 110
    MSG_IDENTIFY_LONGFLAGS = 111
    MSG_IDENTIFY_TERMINFO = 112
    MSG_COMMAND = 200
    MSG_DETACH = 201
    MSG_DETACHKILL = 202
    MSG_EXIT = 203
    MSG_EXITED = 204
    MSG_EXITING = 205
    MSG_LOCK = 206
    MSG_READY = 207
    MSG_RESIZE = 208
    MSG_SHELL = 209
    MSG_SHUTDOWN = 210
    MSG_OLDSTDERR = 211
    MSG_OLDSTDIN = 212
    MSG_OLDSTDOUT = 213
    MSG_SUSPEND = 214
    MSG_UNLOCK = 215
    MSG_WAKEUP = 216
    MSG_EXEC = 217
    MSG_FLAGS = 218
    MSG_READ_OPEN = 300
    MSG_READ = 301
    MSG_READ_DONE = 302
    MSG_WRITE_OPEN = 303
    MSG_WRITE = 304
    MSG_WRITE_READY = 305
    MSG_WRITE_CLOSE = 306
    MSG_READ_CANCEL = 307


@dataclasses.dataclass(frozen=True)
class WriteOpenMessage:
    """Parsed ``MSG_WRITE_OPEN`` payload."""

    stream: int
    fd: int
    flags: int
    path: str


@dataclasses.dataclass(frozen=True)
class WriteDataMessage:
    """Parsed ``MSG_WRITE`` payload."""

    stream: int
    data: bytes


@dataclasses.dataclass(frozen=True)
class WriteReadyMessage:
    """Parsed ``MSG_WRITE_READY`` payload."""

    stream: int
    error: int


@dataclasses.dataclass(frozen=True)
class WriteCloseMessage:
    """Parsed ``MSG_WRITE_CLOSE`` payload."""

    stream: int


@dataclasses.dataclass(frozen=True)
class ReadOpenMessage:
    """Parsed ``MSG_READ_OPEN`` payload."""

    stream: int
    fd: int
    path: str


@dataclasses.dataclass(frozen=True)
class ReadDoneMessage:
    """Parsed ``MSG_READ_DONE`` payload."""

    stream: int
    error: int


@dataclasses.dataclass(frozen=True)
class ExitMessage:
    """Parsed ``MSG_EXIT`` payload."""

    returncode: int
    message: str | None


@dataclasses.dataclass(frozen=True)
class RawMessage:
    """Payload for message types without a dedicated parser."""

    payload: bytes


ParsedMessage: t.TypeAlias = (
    WriteOpenMessage
    | WriteDataMessage
    | WriteReadyMessage
    | WriteCloseMessage
    | ReadOpenMessage
    | ReadDoneMessage
    | ExitMessage
    | RawMessage
)


class ProtocolV8Codec:
    """Typed codec for tmux binary protocol version 8."""

    version = "8"

    @property
    def msg_version(self) -> int:
        """Return the numeric ``MSG_VERSION`` message type."""
        return int(MessageType.MSG_VERSION)

    @property
    def msg_ready(self) -> int:
        """Return the numeric ``MSG_READY`` message type."""
        return int(MessageType.MSG_READY)

    @property
    def msg_exit(self) -> int:
        """Return the numeric ``MSG_EXIT`` message type."""
        return int(MessageType.MSG_EXIT)

    @property
    def msg_exited(self) -> int:
        """Return the numeric ``MSG_EXITED`` message type."""
        return int(MessageType.MSG_EXITED)

    @property
    def msg_shutdown(self) -> int:
        """Return the numeric ``MSG_SHUTDOWN`` message type."""
        return int(MessageType.MSG_SHUTDOWN)

    @property
    def msg_flags(self) -> int:
        """Return the numeric ``MSG_FLAGS`` message type."""
        return int(MessageType.MSG_FLAGS)

    @property
    def msg_write_open(self) -> int:
        """Return the numeric ``MSG_WRITE_OPEN`` message type."""
        return int(MessageType.MSG_WRITE_OPEN)

    @property
    def msg_write(self) -> int:
        """Return the numeric ``MSG_WRITE`` message type."""
        return int(MessageType.MSG_WRITE)

    @property
    def msg_write_close(self) -> int:
        """Return the numeric ``MSG_WRITE_CLOSE`` message type."""
        return int(MessageType.MSG_WRITE_CLOSE)

    @property
    def msg_read_open(self) -> int:
        """Return the numeric ``MSG_READ_OPEN`` message type."""
        return int(MessageType.MSG_READ_OPEN)

    @property
    def msg_exiting(self) -> int:
        """Return the numeric ``MSG_EXITING`` message type."""
        return int(MessageType.MSG_EXITING)

    def frame_message(
        self,
        msg_type: int | MessageType,
        payload: bytes,
        *,
        peer_id: int,
        fd: int | None = None,
    ) -> ImsgFrame:
        """Return a typed imsg frame."""
        length = IMSG_HEADER_SIZE + len(payload)
        if length > MAX_IMSGSIZE:
            msg = f"tmux imsg payload too large: {len(payload)} bytes"
            raise exc.TmuxProtocolError(msg)
        return ImsgFrame(
            header=ImsgHeader(
                msg_type=int(msg_type),
                length=length,
                peer_id=peer_id,
                pid=0,
                has_fd=fd is not None,
            ),
            payload=payload,
            fd=fd,
        )

    def pack_frame(self, frame: ImsgFrame) -> bytes:
        """Return wire bytes for a typed imsg frame."""
        expected_payload_len = frame.header.length - IMSG_HEADER_SIZE
        if expected_payload_len != len(frame.payload):
            msg = (
                "tmux imsg frame length does not match payload size: "
                f"{frame.header.length} != {IMSG_HEADER_SIZE + len(frame.payload)}"
            )
            raise exc.TmuxProtocolError(msg)
        if frame.header.has_fd != (frame.fd is not None):
            msg = "tmux imsg frame FD marker does not match descriptor"
            raise exc.TmuxProtocolError(msg)

        encoded_length = frame.header.length
        if frame.header.has_fd:
            encoded_length |= IMSG_FD_MARK
        header = _HEADER.pack(
            frame.header.msg_type,
            encoded_length,
            frame.header.peer_id,
            frame.header.pid,
        )
        return header + frame.payload

    def pack_message(
        self,
        msg_type: int,
        payload: bytes,
        *,
        peer_id: int,
    ) -> bytes:
        """Return a framed tmux imsg message without an attached FD."""
        return self.pack_frame(
            self.frame_message(msg_type, payload, peer_id=peer_id),
        )

    def unpack_header(self, data: bytes) -> ImsgHeader:
        """Decode and validate a tmux imsg header."""
        if len(data) != IMSG_HEADER_SIZE:
            msg = f"tmux imsg header must be {IMSG_HEADER_SIZE} bytes"
            raise exc.TmuxProtocolError(msg)

        msg_type, encoded_length, peer_id, pid = _HEADER.unpack(data)
        has_fd = bool(encoded_length & IMSG_FD_MARK)
        length = encoded_length & ~IMSG_FD_MARK
        if length < IMSG_HEADER_SIZE or length > MAX_IMSGSIZE:
            msg = f"Invalid tmux imsg length: {length}"
            raise exc.TmuxProtocolError(msg)
        return ImsgHeader(
            msg_type=msg_type,
            length=length,
            peer_id=peer_id,
            pid=pid,
            has_fd=has_fd,
        )

    def identify_messages(
        self,
        *,
        cwd: str,
        term: str,
        tty_name: str,
        client_pid: int,
        environ: dict[str, str],
        flags: int = 0,
        features: int = 0,
        stdin_fd: int | None = None,
        stdout_fd: int | None = None,
    ) -> list[ImsgFrame]:
        """Build the identify handshake messages for a tmux client."""
        peer_id = int(self.version)
        messages = [
            self.frame_message(
                MessageType.MSG_IDENTIFY_LONGFLAGS,
                _UINT64.pack(flags),
                peer_id=peer_id,
            ),
            self.frame_message(
                MessageType.MSG_IDENTIFY_LONGFLAGS,
                _UINT64.pack(flags),
                peer_id=peer_id,
            ),
            self.frame_message(
                MessageType.MSG_IDENTIFY_TERM,
                _c_string(term),
                peer_id=peer_id,
            ),
            self.frame_message(
                MessageType.MSG_IDENTIFY_FEATURES,
                _INT32.pack(features),
                peer_id=peer_id,
            ),
            self.frame_message(
                MessageType.MSG_IDENTIFY_TTYNAME,
                _c_string(tty_name),
                peer_id=peer_id,
            ),
            self.frame_message(
                MessageType.MSG_IDENTIFY_CWD,
                _c_string(cwd),
                peer_id=peer_id,
            ),
            self.frame_message(
                MessageType.MSG_IDENTIFY_STDIN,
                b"",
                peer_id=peer_id,
                fd=stdin_fd,
            ),
            self.frame_message(
                MessageType.MSG_IDENTIFY_STDOUT,
                b"",
                peer_id=peer_id,
                fd=stdout_fd,
            ),
            self.frame_message(
                MessageType.MSG_IDENTIFY_CLIENTPID,
                _INT32.pack(client_pid),
                peer_id=peer_id,
            ),
        ]
        for key, value in environ.items():
            encoded = _c_string(f"{key}={value}")
            if len(encoded) > MAX_IMSGSIZE - IMSG_HEADER_SIZE:
                continue
            messages.append(
                self.frame_message(
                    MessageType.MSG_IDENTIFY_ENVIRON,
                    encoded,
                    peer_id=peer_id,
                ),
            )
        messages.append(
            self.frame_message(
                MessageType.MSG_IDENTIFY_DONE,
                b"",
                peer_id=peer_id,
            ),
        )
        return messages

    def command_message(self, argv: tuple[str, ...], *, peer_id: int) -> ImsgFrame:
        """Build a ``MSG_COMMAND`` frame."""
        payload = _INT32.pack(len(argv)) + b"".join(_c_string(arg) for arg in argv)
        return self.frame_message(
            MessageType.MSG_COMMAND,
            payload,
            peer_id=peer_id,
        )

    def parse_message(
        self,
        msg_type: int,
        payload: bytes,
        *,
        peer_id: int,
        pid: int,
    ) -> ParsedMessage:
        """Parse a typed tmux message payload."""
        del peer_id, pid
        if msg_type == int(MessageType.MSG_WRITE_OPEN):
            _require_min_size(payload, _WRITE_OPEN.size, "MSG_WRITE_OPEN")
            stream, fd, flags = _WRITE_OPEN.unpack_from(payload)
            path = _decode_c_string(payload[_WRITE_OPEN.size :])
            return WriteOpenMessage(stream=stream, fd=fd, flags=flags, path=path)
        if msg_type == int(MessageType.MSG_WRITE):
            _require_min_size(payload, _WRITE_DATA.size, "MSG_WRITE")
            (stream,) = _WRITE_DATA.unpack_from(payload)
            return WriteDataMessage(stream=stream, data=payload[_WRITE_DATA.size :])
        if msg_type == int(MessageType.MSG_WRITE_READY):
            _require_exact_size(payload, _WRITE_READY.size, "MSG_WRITE_READY")
            stream, error = _WRITE_READY.unpack(payload)
            return WriteReadyMessage(stream=stream, error=error)
        if msg_type == int(MessageType.MSG_WRITE_CLOSE):
            _require_exact_size(payload, _WRITE_CLOSE.size, "MSG_WRITE_CLOSE")
            (stream,) = _WRITE_CLOSE.unpack(payload)
            return WriteCloseMessage(stream=stream)
        if msg_type == int(MessageType.MSG_READ_OPEN):
            _require_min_size(payload, _READ_OPEN.size, "MSG_READ_OPEN")
            stream, fd = _READ_OPEN.unpack_from(payload)
            path = _decode_c_string(payload[_READ_OPEN.size :])
            return ReadOpenMessage(stream=stream, fd=fd, path=path)
        if msg_type == int(MessageType.MSG_READ_DONE):
            _require_exact_size(payload, _READ_DONE.size, "MSG_READ_DONE")
            stream, error = _READ_DONE.unpack(payload)
            return ReadDoneMessage(stream=stream, error=error)
        if msg_type == int(MessageType.MSG_EXIT):
            return _parse_exit_message(payload)
        return RawMessage(payload=payload)

    def exit_status_from_message(self, message: object) -> _ExitStatus | None:
        """Return exit metadata if the parsed message encodes it."""
        if isinstance(message, ExitMessage):
            return message.returncode, message.message
        return None

    def write_open_stream(self, message: object) -> int | None:
        """Return the stream id from a ``MSG_WRITE_OPEN`` message."""
        if isinstance(message, WriteOpenMessage):
            return message.stream
        return None

    def write_payload(self, message: object) -> tuple[int, bytes] | None:
        """Return stream id and bytes from a ``MSG_WRITE`` message."""
        if isinstance(message, WriteDataMessage):
            return message.stream, message.data
        return None

    def write_close_stream(self, message: object) -> int | None:
        """Return the closed stream id from a ``MSG_WRITE_CLOSE`` message."""
        if isinstance(message, WriteCloseMessage):
            return message.stream
        return None

    def read_open_stream(self, message: object) -> int | None:
        """Return the stream id from a ``MSG_READ_OPEN`` message."""
        if isinstance(message, ReadOpenMessage):
            return message.stream
        return None

    def write_ready_message(
        self,
        stream: int,
        error_code: int,
        *,
        peer_id: int,
    ) -> ImsgFrame:
        """Build a ``MSG_WRITE_READY`` reply."""
        return self.frame_message(
            MessageType.MSG_WRITE_READY,
            _WRITE_READY.pack(stream, error_code),
            peer_id=peer_id,
        )

    def read_done_message(
        self,
        stream: int,
        error_code: int,
        *,
        peer_id: int,
    ) -> ImsgFrame:
        """Build a ``MSG_READ_DONE`` reply."""
        return self.frame_message(
            MessageType.MSG_READ_DONE,
            _READ_DONE.pack(stream, error_code),
            peer_id=peer_id,
        )

    def exiting_message(self, *, peer_id: int) -> ImsgFrame:
        """Build a ``MSG_EXITING`` notification."""
        return self.frame_message(MessageType.MSG_EXITING, b"", peer_id=peer_id)


def _c_string(value: str) -> bytes:
    return value.encode("utf-8") + b"\0"


def _decode_c_string(data: bytes) -> str:
    if not data:
        return ""
    if data[-1] != 0:
        msg = "tmux imsg string payload is not NUL terminated"
        raise exc.TmuxProtocolError(msg)
    return data[:-1].decode("utf-8", errors="backslashreplace")


def _require_min_size(payload: bytes, min_size: int, name: str) -> None:
    if len(payload) < min_size:
        msg = f"bad {name} payload size: {len(payload)}"
        raise exc.TmuxProtocolError(msg)


def _require_exact_size(payload: bytes, expected_size: int, name: str) -> None:
    if len(payload) != expected_size:
        msg = f"bad {name} payload size: {len(payload)}"
        raise exc.TmuxProtocolError(msg)


def _parse_exit_message(payload: bytes) -> ExitMessage:
    if len(payload) < _INT32.size and payload:
        msg = "bad MSG_EXIT payload size"
        raise exc.TmuxProtocolError(msg)

    returncode = 0
    message: str | None = None
    if len(payload) >= _INT32.size:
        (returncode,) = _INT32.unpack_from(payload)
    if len(payload) > _INT32.size:
        message = _decode_c_string(payload[_INT32.size :]) or None
    return ExitMessage(returncode=returncode, message=message)


register_imsg_protocol("8", ProtocolV8Codec)

__all__ = (
    "IMSG_FD_MARK",
    "IMSG_HEADER_SIZE",
    "MAX_IMSGSIZE",
    "ExitMessage",
    "MessageType",
    "ParsedMessage",
    "ProtocolV8Codec",
    "RawMessage",
    "ReadDoneMessage",
    "ReadOpenMessage",
    "WriteCloseMessage",
    "WriteDataMessage",
    "WriteOpenMessage",
    "WriteReadyMessage",
)
