"""Shared primitives for tmux imsg protocol engines."""

from __future__ import annotations

import array
import contextlib
import errno
import logging
import os
import pathlib
import selectors
import shutil
import socket
import typing as t

from libtmux import exc
from libtmux.engines.base import CommandRequest, CommandResult
from libtmux.engines.imsg.types import ImsgFrame, ImsgHeader
from libtmux.engines.registry import create_imsg_protocol, register_engine

from . import v8 as _v8  # noqa: F401

logger = logging.getLogger(__name__)

_MAX_IMSGSIZE = 16384
_IMSG_HEADER_SIZE = 16
_ExitStatus = tuple[int, str | None]
_CLIENT_UTF8 = 0x10000


class ImsgProtocolCodec(t.Protocol):
    """Protocol for versioned tmux imsg codecs."""

    version: str

    def pack_frame(self, frame: ImsgFrame) -> bytes:
        """Return wire bytes for a typed imsg frame."""

    def pack_message(self, msg_type: int, payload: bytes, *, peer_id: int) -> bytes:
        """Return a framed tmux imsg message without an attached FD."""

    def unpack_header(self, data: bytes) -> ImsgHeader:
        """Decode a tmux imsg header."""

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

    def command_message(self, argv: tuple[str, ...], *, peer_id: int) -> ImsgFrame:
        """Build a ``MSG_COMMAND`` frame."""

    def parse_message(
        self,
        msg_type: int,
        payload: bytes,
        *,
        peer_id: int,
        pid: int,
    ) -> object:
        """Parse a typed tmux message payload."""

    def exit_status_from_message(
        self,
        message: object,
    ) -> _ExitStatus | None:
        """Return exit metadata if the parsed message encodes it."""

    def write_open_stream(self, message: object) -> int | None:
        """Return the declared stream id from a ``MSG_WRITE_OPEN`` message."""

    def write_payload(self, message: object) -> tuple[int, bytes] | None:
        """Return stream id and bytes from a ``MSG_WRITE`` message."""

    def write_close_stream(self, message: object) -> int | None:
        """Return the closed stream id from a ``MSG_WRITE_CLOSE`` message."""

    def read_open_stream(self, message: object) -> int | None:
        """Return the declared stream id from a ``MSG_READ_OPEN`` message."""

    def write_ready_message(
        self,
        stream: int,
        error_code: int,
        *,
        peer_id: int,
    ) -> ImsgFrame:
        """Build a ``MSG_WRITE_READY`` reply."""

    def read_done_message(
        self,
        stream: int,
        error_code: int,
        *,
        peer_id: int,
    ) -> ImsgFrame:
        """Build a ``MSG_READ_DONE`` reply."""

    @property
    def msg_version(self) -> int:
        """Return the numeric ``MSG_VERSION`` message type."""

    @property
    def msg_ready(self) -> int:
        """Return the numeric ``MSG_READY`` message type."""

    @property
    def msg_exit(self) -> int:
        """Return the numeric ``MSG_EXIT`` message type."""

    @property
    def msg_exited(self) -> int:
        """Return the numeric ``MSG_EXITED`` message type."""

    @property
    def msg_shutdown(self) -> int:
        """Return the numeric ``MSG_SHUTDOWN`` message type."""

    @property
    def msg_flags(self) -> int:
        """Return the numeric ``MSG_FLAGS`` message type."""

    @property
    def msg_write_open(self) -> int:
        """Return the numeric ``MSG_WRITE_OPEN`` message type."""

    @property
    def msg_write(self) -> int:
        """Return the numeric ``MSG_WRITE`` message type."""

    @property
    def msg_write_close(self) -> int:
        """Return the numeric ``MSG_WRITE_CLOSE`` message type."""

    @property
    def msg_read_open(self) -> int:
        """Return the numeric ``MSG_READ_OPEN`` message type."""

    @property
    def msg_exiting(self) -> int:
        """Return the numeric ``MSG_EXITING`` message type."""

    def exiting_message(self, *, peer_id: int) -> ImsgFrame:
        """Build a ``MSG_EXITING`` notification."""


class _ImsgCommandArgs(t.NamedTuple):
    """Parsed tmux CLI arguments needed by the imsg engine."""

    global_args: tuple[str, ...]
    command_argv: tuple[str, ...]
    socket_name: str | None
    socket_path: str | None
    config_file: str | None
    command_name: str | None


class ImsgEngine:
    """Execute tmux commands via the native binary imsg socket protocol."""

    _startserver_commands = frozenset({"new-session", "start-server"})

    def __init__(self, protocol_version: str | int | None = None) -> None:
        self.protocol_version = (
            str(protocol_version) if protocol_version is not None else None
        )
        self._resolved_tmux_bin: str | None = None

    def run(self, request: CommandRequest) -> CommandResult:
        """Execute a tmux command over the server socket."""
        tmux_bin = request.tmux_bin or self._resolve_tmux_bin()
        parsed = self._parse_args(request.args)
        cmd = [tmux_bin, *parsed.global_args, *parsed.command_argv]

        if parsed.command_name is None or parsed.command_name == "-V":
            return self._run_local_command(cmd)

        socket_path = self._resolve_socket_path(parsed)
        if parsed.command_name == "start-server":
            return self._run_local_command(cmd)
        if parsed.command_name in self._startserver_commands and not _server_available(
            socket_path
        ):
            return self._run_local_command(cmd)

        peer_id = int(self.protocol_version or create_imsg_protocol().version)
        retries_remaining = 1

        while True:
            sock: socket.socket | None = None
            codec = create_imsg_protocol(peer_id)
            try:
                sock = self._connect(socket_path=socket_path)
                return self._run_socket_command(
                    sock=sock,
                    codec=codec,
                    peer_id=peer_id,
                    command_argv=parsed.command_argv,
                    cmd=cmd,
                )
            except _NoServerError as error:
                if parsed.command_name in self._startserver_commands:
                    return self._run_local_command(cmd)
                return CommandResult(
                    cmd=cmd,
                    stdout=[],
                    stderr=[error.message],
                    returncode=1,
                    process=None,
                )
            except (BrokenPipeError, ConnectionResetError) as error:
                # Server began shutdown between connect() and the first
                # send/recv: the socket file still exists so connect succeeded,
                # but the kernel returns EPIPE/ECONNRESET on the first I/O.
                # Mirror tmux's CLIENT_EXIT_LOST_SERVER behavior — present a
                # clean "no server running" CommandResult instead of leaking
                # the transport exception.
                if parsed.command_name in self._startserver_commands:
                    return self._run_local_command(cmd)
                return CommandResult(
                    cmd=cmd,
                    stdout=[],
                    stderr=[self._no_server_message(socket_path, error)],
                    returncode=1,
                    process=None,
                )
            except _ProtocolVersionMismatch as mismatch:
                if retries_remaining == 0:
                    engine_name = "imsg"
                    raise exc.UnsupportedProtocolVersion(
                        engine_name,
                        mismatch.server_version,
                    ) from None
                retries_remaining -= 1
                peer_id = int(mismatch.server_version)
                self.protocol_version = mismatch.server_version
            finally:
                if sock is not None:
                    sock.close()

    def _resolve_tmux_bin(self) -> str:
        """Return the tmux binary path, memoized per engine instance.

        ``shutil.which`` walks ``$PATH`` on every call (~50µs); the engine
        invokes it on the hot path of every command, so caching the
        result for the lifetime of the engine instance is a free win.
        ``TmuxCommandNotFound`` is intentionally not memoized.
        """
        if self._resolved_tmux_bin is None:
            resolved = shutil.which("tmux")
            if resolved is None:
                raise exc.TmuxCommandNotFound
            self._resolved_tmux_bin = resolved
        return self._resolved_tmux_bin

    def run_batch(
        self,
        requests: t.Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Trivial loop — imsg engine opens a fresh socket per call, no batching benefit.

        Provided for uniform API with the control-mode engine; callers
        can use ``run_batch`` regardless of engine and get the right
        ordered list of results.
        """
        return [self.run(req) for req in requests]

    def _parse_args(self, args: tuple[str, ...]) -> _ImsgCommandArgs:
        global_args: list[str] = []
        command_argv: list[str] = []
        socket_name: str | None = None
        socket_path: str | None = None
        config_file: str | None = None

        index = 0
        while index < len(args):
            arg = args[index]
            if arg == "-V":
                command_argv.append(arg)
                break
            if arg in {"-L", "-S", "-f"}:
                if index + 1 >= len(args):
                    command_argv.append(arg)
                    break
                value = args[index + 1]
                global_args.extend((arg, value))
                if arg == "-L":
                    socket_name = value
                elif arg == "-S":
                    socket_path = value
                else:
                    config_file = value
                index += 2
                continue
            if arg.startswith("-L") and len(arg) > 2:
                socket_name = arg[2:]
                global_args.append(arg)
                index += 1
                continue
            if arg.startswith("-S") and len(arg) > 2:
                socket_path = arg[2:]
                global_args.append(arg)
                index += 1
                continue
            if arg.startswith("-f") and len(arg) > 2:
                config_file = arg[2:]
                global_args.append(arg)
                index += 1
                continue
            if arg in {"-2", "-8"}:
                global_args.append(arg)
                index += 1
                continue

            command_argv.extend(args[index:])
            break

        command_name = command_argv[0] if command_argv else None
        return _ImsgCommandArgs(
            global_args=tuple(global_args),
            command_argv=tuple(command_argv),
            socket_name=socket_name,
            socket_path=socket_path,
            config_file=config_file,
            command_name=command_name,
        )

    def _resolve_socket_path(self, parsed: _ImsgCommandArgs) -> str:
        if parsed.socket_path is not None:
            return parsed.socket_path

        socket_name = parsed.socket_name or "default"
        tmux_tmpdir = pathlib.Path(os.getenv("TMUX_TMPDIR", "/tmp"))
        return str(tmux_tmpdir / f"tmux-{os.geteuid()}" / socket_name)

    def _connect(
        self,
        *,
        socket_path: str,
    ) -> socket.socket:
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(socket_path)
        except OSError as error:
            sock.close()
            if error.errno not in {errno.ENOENT, errno.ECONNREFUSED}:
                raise
            raise _NoServerError(
                self._no_server_message(socket_path, error),
            ) from error
        return sock

    def _no_server_message(self, socket_path: str, error: OSError) -> str:
        if error.errno == errno.ECONNREFUSED:
            return f"error connecting to {socket_path}"
        return f"no server running on {socket_path}"

    def _client_flags(self) -> int:
        if os.environ.get("TMUX"):
            return _CLIENT_UTF8

        locale = (
            os.environ.get("LC_ALL")
            or os.environ.get("LC_CTYPE")
            or os.environ.get("LANG")
            or ""
        )
        locale = locale.upper()
        if "UTF-8" in locale or "UTF8" in locale:
            return _CLIENT_UTF8
        return 0

    def _run_local_command(self, cmd: list[str]) -> CommandResult:
        exit_code, stdout, stderr = _spawn_and_capture(cmd)
        return CommandResult(
            cmd=cmd,
            stdout=stdout,
            stderr=stderr,
            returncode=exit_code,
            process=None,
        )

    def _run_socket_command(
        self,
        *,
        sock: socket.socket,
        codec: ImsgProtocolCodec,
        peer_id: int,
        command_argv: tuple[str, ...],
        cmd: list[str],
    ) -> CommandResult:
        stdin_fd = _duplicate_fd(0)
        stdout_fd = _duplicate_fd(1)
        identify_frames = codec.identify_messages(
            cwd=str(pathlib.Path.cwd()),
            term=os.environ.get("TERM", "unknown") or "unknown",
            tty_name="",
            client_pid=os.getpid(),
            environ=dict(os.environ),
            flags=self._client_flags(),
            features=0,
            stdin_fd=stdin_fd,
            stdout_fd=stdout_fd,
        )
        logger.debug(
            "sending imsg identify burst",
            extra={
                "tmux_protocol_version": codec.version,
                "tmux_identify_frames": len(identify_frames),
                "tmux_command_argv": list(command_argv),
            },
        )

        stdout_streams: set[int] = set()
        stderr_streams: set[int] = set()
        stdout_buffer = bytearray()
        stderr_buffer = bytearray()
        exit_code = 0
        exit_message: str | None = None
        seen_exit = False

        transport = _SelectorSocketTransport(sock)
        try:
            transport.send_frames(codec, identify_frames)
            command_frame = codec.command_message(command_argv, peer_id=peer_id)
            transport.send_frame(codec, command_frame)

            while True:
                frame = transport.recv_frame(codec)
                msg_type = frame.header.msg_type
                peer = frame.header.peer_id
                pid = frame.header.pid
                payload = frame.payload
                logger.debug(
                    "received imsg message",
                    extra={
                        "tmux_protocol_version": codec.version,
                        "tmux_message_type": msg_type,
                        "tmux_message_peer": peer,
                        "tmux_message_pid": pid,
                        "tmux_message_len": len(payload),
                        "tmux_message_has_fd": frame.header.has_fd,
                        "tmux_command_argv": list(command_argv),
                    },
                )
                if msg_type == codec.msg_version:
                    _close_fd(frame.fd)
                    raise _ProtocolVersionMismatch(str(peer & 0xFF))

                try:
                    message: object = codec.parse_message(
                        msg_type,
                        payload,
                        peer_id=peer,
                        pid=pid,
                    )
                finally:
                    _close_fd(frame.fd)

                if msg_type == codec.msg_ready:
                    continue
                if msg_type == codec.msg_flags:
                    continue

                stream = codec.write_open_stream(message)
                if stream is not None:
                    if stream == 2:
                        stderr_streams.add(stream)
                    else:
                        stdout_streams.add(stream)
                    transport.send_frame(
                        codec,
                        codec.write_ready_message(stream, 0, peer_id=peer_id),
                    )
                    continue

                payload_data = codec.write_payload(message)
                if payload_data is not None:
                    stream_id, data = payload_data
                    if stream_id in stderr_streams:
                        stderr_buffer.extend(data)
                    else:
                        stdout_buffer.extend(data)
                    continue

                close_stream = codec.write_close_stream(message)
                if close_stream is not None:
                    continue

                read_stream = codec.read_open_stream(message)
                if read_stream is not None:
                    transport.send_frame(
                        codec,
                        codec.read_done_message(
                            read_stream,
                            errno.EBADF,
                            peer_id=peer_id,
                        ),
                    )
                    continue

                exit_status = codec.exit_status_from_message(message)
                if exit_status is not None:
                    exit_code, exit_message = exit_status
                    seen_exit = True
                    transport.send_frame(
                        codec,
                        codec.exiting_message(peer_id=peer_id),
                    )
                    continue

                if msg_type == codec.msg_shutdown:
                    exit_code = 1
                    seen_exit = True
                    transport.send_frame(
                        codec,
                        codec.exiting_message(peer_id=peer_id),
                    )
                    continue

                if msg_type == codec.msg_exited:
                    break

                if seen_exit:
                    break
        finally:
            transport.close()

        stdout_lines = _split_output(bytes(stdout_buffer))
        stderr_lines = _split_output(bytes(stderr_buffer))
        if exit_message:
            stderr_lines.append(exit_message)
        if "has-session" in cmd and stderr_lines and not stdout_lines:
            stdout_lines = [stderr_lines[0]]

        return CommandResult(
            cmd=cmd,
            stdout=stdout_lines,
            stderr=stderr_lines,
            returncode=exit_code,
            process=None,
        )


class _ProtocolVersionMismatch(RuntimeError):
    """Internal signal for retrying with a negotiated protocol version."""

    def __init__(self, server_version: str) -> None:
        super().__init__(server_version)
        self.server_version = server_version


class _NoServerError(RuntimeError):
    """Internal signal for commands against a missing tmux socket."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class _SelectorSocketTransport:
    """Selector-backed imsg transport for Unix domain sockets."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.sock.setblocking(False)
        self._selector = selectors.DefaultSelector()
        self._selector.register(sock, selectors.EVENT_READ)
        self._buffer = bytearray()
        self._pending_fds: list[int] = []

    def close(self) -> None:
        """Close selector state and any unclaimed descriptors."""
        with contextlib.suppress(KeyError, ValueError):
            self._selector.unregister(self.sock)
        self._selector.close()
        for fd in self._pending_fds:
            _close_fd(fd)
        self._pending_fds.clear()

    def send_frames(
        self,
        codec: ImsgProtocolCodec,
        frames: list[ImsgFrame],
    ) -> None:
        """Send a sequence of frames and close unsent descriptors on failure."""
        sent = 0
        try:
            for frame in frames:
                self.send_frame(codec, frame)
                sent += 1
        finally:
            for frame in frames[sent:]:
                _close_fd(frame.fd)

    def send_frame(self, codec: ImsgProtocolCodec, frame: ImsgFrame) -> None:
        """Send one imsg frame, including an optional SCM_RIGHTS descriptor."""
        data = codec.pack_frame(frame)
        if frame.fd is not None:
            self._send_frame_with_fd(data, frame.fd)
            return
        self._send_all(data)

    def recv_frame(self, codec: ImsgProtocolCodec) -> ImsgFrame:
        """Receive one complete imsg frame."""
        while len(self._buffer) < _IMSG_HEADER_SIZE:
            self._recv_more()

        header = codec.unpack_header(bytes(self._buffer[:_IMSG_HEADER_SIZE]))
        while len(self._buffer) < header.length:
            self._recv_more()

        payload = bytes(self._buffer[_IMSG_HEADER_SIZE : header.length])
        del self._buffer[: header.length]

        fd: int | None = None
        if header.has_fd and self._pending_fds:
            fd = self._pending_fds.pop(0)

        return ImsgFrame(header=header, payload=payload, fd=fd)

    def _wait_for(self, event: int) -> None:
        self._selector.modify(self.sock, event)
        self._selector.select()

    def _send_all(self, data: bytes) -> None:
        offset = 0
        while offset < len(data):
            self._wait_for(selectors.EVENT_WRITE)
            try:
                sent = self.sock.send(data[offset:])
            except BlockingIOError:
                continue
            if sent == 0:
                msg = "tmux socket closed during protocol write"
                raise exc.TmuxProtocolError(msg)
            offset += sent

    def _send_frame_with_fd(self, data: bytes, fd: int) -> None:
        fds = array.array("i", [fd])
        ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, fds.tobytes())]
        try:
            while True:
                self._wait_for(selectors.EVENT_WRITE)
                try:
                    sent = self.sock.sendmsg([data], ancillary)
                except BlockingIOError:
                    continue
                break
            if sent != len(data):
                msg = "tmux imsg frame with FD was partially written"
                raise exc.TmuxProtocolError(msg)
        finally:
            _close_fd(fd)

    def _recv_more(self) -> None:
        self._wait_for(selectors.EVENT_READ)
        fd_size = array.array("i").itemsize
        try:
            data, ancillary, _flags, _addr = self.sock.recvmsg(
                65535,
                socket.CMSG_SPACE(fd_size),
            )
        except BlockingIOError:
            return
        if not data:
            msg = "tmux socket closed during protocol exchange"
            raise exc.TmuxProtocolError(msg)

        self._buffer.extend(data)
        for level, msg_type, cmsg_data in ancillary:
            if level != socket.SOL_SOCKET or msg_type != socket.SCM_RIGHTS:
                continue
            fds = array.array("i")
            fds.frombytes(cmsg_data[: len(cmsg_data) - (len(cmsg_data) % fd_size)])
            for index, fd in enumerate(fds):
                if index == 0:
                    self._pending_fds.append(fd)
                else:
                    _close_fd(fd)


def _spawn_and_capture(command: list[str]) -> tuple[int, list[str], list[str]]:
    """Run a command without subprocess and capture its output."""
    stdout_read, stdout_write = os.pipe()
    stderr_read, stderr_write = os.pipe()
    file_actions = [
        (os.POSIX_SPAWN_DUP2, stdout_write, 1),
        (os.POSIX_SPAWN_DUP2, stderr_write, 2),
        (os.POSIX_SPAWN_CLOSE, stdout_read),
        (os.POSIX_SPAWN_CLOSE, stderr_read),
    ]

    try:
        if "/" in command[0]:
            pid = os.posix_spawn(
                command[0],
                command,
                os.environ,
                file_actions=file_actions,
            )
        else:
            pid = os.posix_spawnp(
                command[0],
                command,
                os.environ,
                file_actions=file_actions,
            )
    except FileNotFoundError:
        raise exc.TmuxCommandNotFound from None
    finally:
        os.close(stdout_write)
        os.close(stderr_write)

    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []

    os.set_blocking(stdout_read, False)
    os.set_blocking(stderr_read, False)

    selector = selectors.DefaultSelector()
    streams = {
        stdout_read: stdout_chunks,
        stderr_read: stderr_chunks,
    }
    selector.register(stdout_read, selectors.EVENT_READ)
    selector.register(stderr_read, selectors.EVENT_READ)

    try:
        while streams:
            for key, _mask in selector.select():
                fd = key.fd
                try:
                    chunk = os.read(fd, 65535)
                except BlockingIOError:
                    continue
                if chunk:
                    streams[fd].append(chunk)
                    continue
                selector.unregister(fd)
                del streams[fd]
    finally:
        selector.close()

    os.close(stdout_read)
    os.close(stderr_read)
    _pid, status = os.waitpid(pid, 0)
    exit_code = os.waitstatus_to_exitcode(status)

    stdout_lines = _split_output(b"".join(stdout_chunks))
    stderr_lines = _split_output(b"".join(stderr_chunks))
    return exit_code, stdout_lines, stderr_lines


def _duplicate_fd(fd: int) -> int | None:
    """Duplicate a descriptor for SCM_RIGHTS ownership transfer."""
    with contextlib.suppress(OSError):
        return os.dup(fd)
    return None


def _close_fd(fd: int | None) -> None:
    """Close a descriptor if one is present."""
    if fd is not None:
        with contextlib.suppress(OSError):
            os.close(fd)


def _split_output(data: bytes) -> list[str]:
    """Split tmux output into newline-delimited text lines."""
    text = data.decode("utf-8", errors="backslashreplace")
    lines = text.split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def _server_available(socket_path: str) -> bool:
    """Return whether a tmux server is currently listening on the socket path."""
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.connect(socket_path)
    except OSError:
        return False
    finally:
        probe.close()
    return True


register_engine("imsg", ImsgEngine)
