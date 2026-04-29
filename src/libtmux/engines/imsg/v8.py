"""tmux imsg protocol version 8."""

from __future__ import annotations

import enum
import struct
from dataclasses import dataclass

from libtmux.engines.registry import register_imsg_protocol

_HEADER = struct.Struct("=IIII")
_INT32 = struct.Struct("=i")
_UINT32 = struct.Struct("=I")
_UINT64 = struct.Struct("=Q")
_WRITE_OPEN = struct.Struct("=iii")
_WRITE_DATA = struct.Struct("=i")
_WRITE_READY = struct.Struct("=ii")
_WRITE_CLOSE = struct.Struct("=i")
_READ_OPEN = struct.Struct("=ii")
_READ_DONE = struct.Struct("=ii")
_ExitStatus = tuple[int, str | None]


class _MessageType(enum.IntEnum):
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


@dataclass(frozen=True)
class _WriteOpenMessage:
    stream: int
    fd: int
    flags: int
    path: str


@dataclass(frozen=True)
class _WriteDataMessage:
    stream: int
    data: bytes


@dataclass(frozen=True)
class _WriteReadyMessage:
    stream: int
    error: int


@dataclass(frozen=True)
class _WriteCloseMessage:
    stream: int


@dataclass(frozen=True)
class _ReadOpenMessage:
    stream: int
    fd: int
    path: str


@dataclass(frozen=True)
class _ReadDoneMessage:
    stream: int
    error: int


@dataclass(frozen=True)
class _ExitMessage:
    returncode: int
    message: str | None


@dataclass(frozen=True)
class _RawMessage:
    payload: bytes


class _ProtocolV8Codec:
    """Typed codec for tmux binary protocol version 8."""

    version = "8"

    @property
    def msg_version(self) -> int:
        return int(_MessageType.MSG_VERSION)

    @property
    def msg_ready(self) -> int:
        return int(_MessageType.MSG_READY)

    @property
    def msg_exit(self) -> int:
        return int(_MessageType.MSG_EXIT)

    @property
    def msg_exited(self) -> int:
        return int(_MessageType.MSG_EXITED)

    @property
    def msg_shutdown(self) -> int:
        return int(_MessageType.MSG_SHUTDOWN)

    @property
    def msg_flags(self) -> int:
        return int(_MessageType.MSG_FLAGS)

    @property
    def msg_write_open(self) -> int:
        return int(_MessageType.MSG_WRITE_OPEN)

    @property
    def msg_write(self) -> int:
        return int(_MessageType.MSG_WRITE)

    @property
    def msg_write_close(self) -> int:
        return int(_MessageType.MSG_WRITE_CLOSE)

    @property
    def msg_read_open(self) -> int:
        return int(_MessageType.MSG_READ_OPEN)

    @property
    def msg_exiting(self) -> int:
        return int(_MessageType.MSG_EXITING)

    def pack_message(self, msg_type: int, payload: bytes, *, peer_id: int) -> bytes:
        header = _HEADER.pack(msg_type, _HEADER.size + len(payload), peer_id, 0)
        return header + payload

    def unpack_header(self, data: bytes) -> tuple[int, int, int, int]:
        return _HEADER.unpack(data)

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
    ) -> list[bytes]:
        peer_id = int(self.version)
        messages = [
            self.pack_message(
                int(_MessageType.MSG_IDENTIFY_LONGFLAGS),
                _UINT64.pack(flags),
                peer_id=peer_id,
            ),
            self.pack_message(
                int(_MessageType.MSG_IDENTIFY_LONGFLAGS),
                _UINT64.pack(flags),
                peer_id=peer_id,
            ),
            self.pack_message(
                int(_MessageType.MSG_IDENTIFY_TERM),
                _c_string(term),
                peer_id=peer_id,
            ),
            self.pack_message(
                int(_MessageType.MSG_IDENTIFY_FEATURES),
                _INT32.pack(features),
                peer_id=peer_id,
            ),
            self.pack_message(
                int(_MessageType.MSG_IDENTIFY_TTYNAME),
                _c_string(tty_name),
                peer_id=peer_id,
            ),
            self.pack_message(
                int(_MessageType.MSG_IDENTIFY_CWD),
                _c_string(cwd),
                peer_id=peer_id,
            ),
            self.pack_message(
                int(_MessageType.MSG_IDENTIFY_CLIENTPID),
                _INT32.pack(client_pid),
                peer_id=peer_id,
            ),
        ]
        for key, value in environ.items():
            encoded = _c_string(f"{key}={value}")
            if len(encoded) > 16384 - _HEADER.size:
                continue
            messages.append(
                self.pack_message(
                    int(_MessageType.MSG_IDENTIFY_ENVIRON),
                    encoded,
                    peer_id=peer_id,
                ),
            )
        messages.append(
            self.pack_message(
                int(_MessageType.MSG_IDENTIFY_DONE),
                b"",
                peer_id=peer_id,
            ),
        )
        return messages

    def command_message(self, argv: tuple[str, ...], *, peer_id: int) -> bytes:
        payload = _INT32.pack(len(argv)) + b"".join(_c_string(arg) for arg in argv)
        return self.pack_message(
            int(_MessageType.MSG_COMMAND),
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
    ) -> object:
        del peer_id, pid
        if msg_type == int(_MessageType.MSG_WRITE_OPEN):
            stream, fd, flags = _WRITE_OPEN.unpack_from(payload)
            path = _decode_c_string(payload[_WRITE_OPEN.size :])
            return _WriteOpenMessage(stream=stream, fd=fd, flags=flags, path=path)
        if msg_type == int(_MessageType.MSG_WRITE):
            (stream,) = _WRITE_DATA.unpack_from(payload)
            return _WriteDataMessage(stream=stream, data=payload[_WRITE_DATA.size :])
        if msg_type == int(_MessageType.MSG_WRITE_READY):
            stream, error = _WRITE_READY.unpack(payload)
            return _WriteReadyMessage(stream=stream, error=error)
        if msg_type == int(_MessageType.MSG_WRITE_CLOSE):
            (stream,) = _WRITE_CLOSE.unpack(payload)
            return _WriteCloseMessage(stream=stream)
        if msg_type == int(_MessageType.MSG_READ_OPEN):
            stream, fd = _READ_OPEN.unpack_from(payload)
            path = _decode_c_string(payload[_READ_OPEN.size :])
            return _ReadOpenMessage(stream=stream, fd=fd, path=path)
        if msg_type == int(_MessageType.MSG_READ_DONE):
            stream, error = _READ_DONE.unpack(payload)
            return _ReadDoneMessage(stream=stream, error=error)
        if msg_type == int(_MessageType.MSG_EXIT):
            return _parse_exit_message(payload)
        return _RawMessage(payload=payload)

    def exit_status_from_message(self, message: object) -> _ExitStatus | None:
        if isinstance(message, _ExitMessage):
            return message.returncode, message.message
        return None

    def write_open_stream(self, message: object) -> int | None:
        if isinstance(message, _WriteOpenMessage):
            return message.stream
        return None

    def write_payload(self, message: object) -> tuple[int, bytes] | None:
        if isinstance(message, _WriteDataMessage):
            return message.stream, message.data
        return None

    def write_close_stream(self, message: object) -> int | None:
        if isinstance(message, _WriteCloseMessage):
            return message.stream
        return None

    def read_open_stream(self, message: object) -> int | None:
        if isinstance(message, _ReadOpenMessage):
            return message.stream
        return None

    def write_ready_message(
        self,
        stream: int,
        error_code: int,
        *,
        peer_id: int,
    ) -> bytes:
        return self.pack_message(
            int(_MessageType.MSG_WRITE_READY),
            _WRITE_READY.pack(stream, error_code),
            peer_id=peer_id,
        )

    def read_done_message(
        self,
        stream: int,
        error_code: int,
        *,
        peer_id: int,
    ) -> bytes:
        return self.pack_message(
            int(_MessageType.MSG_READ_DONE),
            _READ_DONE.pack(stream, error_code),
            peer_id=peer_id,
        )

    def exiting_message(self, *, peer_id: int) -> bytes:
        return self.pack_message(int(_MessageType.MSG_EXITING), b"", peer_id=peer_id)


def _c_string(value: str) -> bytes:
    return value.encode("utf-8") + b"\0"


def _decode_c_string(data: bytes) -> str:
    return data.rstrip(b"\0").decode("utf-8", errors="backslashreplace")


def _parse_exit_message(payload: bytes) -> _ExitMessage:
    if len(payload) < _INT32.size and payload:
        msg = "bad MSG_EXIT payload"
        raise ValueError(msg)

    returncode = 0
    message: str | None = None
    if len(payload) >= _INT32.size:
        (returncode,) = _INT32.unpack_from(payload)
    if len(payload) > _INT32.size:
        message = _decode_c_string(payload[_INT32.size :]) or None
    return _ExitMessage(returncode=returncode, message=message)


register_imsg_protocol("8", _ProtocolV8Codec)
