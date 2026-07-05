"""A persistent control-mode (``tmux -C``) engine.

Holds one long-lived ``tmux -C`` connection and pipelines command lines over it,
parsing each command's ``%begin``/``%end``/``%error`` block back into a
:class:`~.base.CommandResult`. Because it returns the same typed result the
subprocess engine does, an operation run through control mode is
indistinguishable -- at the result level -- from one run through a fork-per-call
subprocess.

The parser (:class:`ControlModeParser`) is I/O-free: it consumes bytes and emits
parsed blocks, so it is unit-testable without spawning tmux. ``run_batch`` writes
all command lines at once and collects one block per command, which is the
control engine's advantage over per-call subprocess startup.
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import os
import selectors
import shutil
import subprocess
import threading
import time
import typing as t

from libtmux import exc
from libtmux.common import get_version
from libtmux.experimental.engines.base import CommandResult, render_control_line

if t.TYPE_CHECKING:
    import types
    from collections.abc import Sequence

    from libtmux.experimental.engines.base import CommandRequest

logger = logging.getLogger(__name__)

_BEGIN_PREFIX = b"%begin "
_END_PREFIX = b"%end "
_ERROR_PREFIX = b"%error "
_READ_CHUNK = 65536
_DEFAULT_TIMEOUT = 30.0
_STARTUP_TIMEOUT = 5.0
_GRACEFUL_EXIT_TIMEOUT = 0.5
_TERMINATE_TIMEOUT = 1.0
_GUARD_MIN_PARTS = 3


class ControlModeError(exc.LibTmuxException):
    """The control-mode engine failed (connection, protocol, or timeout)."""


@dataclasses.dataclass(frozen=True, slots=True)
class ControlModeBlock:
    """One ``%begin``/``%end`` or ``%error`` control-mode command block."""

    number: int
    flags: int
    is_error: bool
    body: tuple[bytes, ...]


@dataclasses.dataclass(slots=True)
class _PendingBlock:
    number: int
    flags: int
    body: list[bytes]


class ControlModeParser:
    r"""I/O-free parser for the command-block subset of control mode.

    Examples
    --------
    >>> parser = ControlModeParser()
    >>> parser.feed(b"%begin 1 1 1\nhello\n%end 1 1 1\n")
    >>> [block.body for block in parser.blocks()]
    [(b'hello',)]
    >>> parser.feed(b"%begin 2 2 1\nboom\n%error 2 2 1\n")
    >>> block = parser.blocks()[0]
    >>> block.is_error, block.body
    (True, (b'boom',))
    """

    __slots__ = ("_blocks", "_buffer", "_notifications", "_pending")

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._blocks: list[ControlModeBlock] = []
        self._notifications: list[bytes] = []
        self._pending: _PendingBlock | None = None

    def feed(self, data: bytes) -> None:
        """Consume bytes from tmux stdout."""
        if not data:
            return
        self._buffer.extend(data)
        while True:
            newline = self._buffer.find(b"\n")
            if newline < 0:
                return
            line = bytes(self._buffer[:newline])
            del self._buffer[: newline + 1]
            self._handle_line(line)

    def blocks(self) -> list[ControlModeBlock]:
        """Drain parsed command blocks."""
        blocks, self._blocks = self._blocks, []
        return blocks

    def notifications(self) -> list[bytes]:
        """Drain raw ``%``-notification lines seen outside command blocks.

        Control mode wraps *command output* in ``%begin``/``%end`` blocks but
        emits asynchronous notifications (``%output``, ``%window-add``, ...) as
        bare lines. The sync engine ignores these; the async engine routes them
        to its event stream.
        """
        notifications, self._notifications = self._notifications, []
        return notifications

    def _handle_line(self, line: bytes) -> None:
        if self._pending is not None:
            if _matches_pending_close(line, self._pending.number):
                self._close_block(line)
                return
            self._pending.body.append(line)
            return
        if line.startswith(_BEGIN_PREFIX):
            self._open_block(line)
        elif line.startswith(b"%"):
            self._notifications.append(line)

    def _open_block(self, line: bytes) -> None:
        number, flags = _parse_guard(line, _BEGIN_PREFIX)
        if number is None:
            return
        self._pending = _PendingBlock(number=number, flags=flags or 0, body=[])

    def _close_block(self, line: bytes) -> None:
        pending = self._pending
        self._pending = None
        if pending is None:
            return
        self._blocks.append(
            ControlModeBlock(
                number=pending.number,
                flags=pending.flags,
                is_error=line.startswith(_ERROR_PREFIX),
                body=tuple(pending.body),
            ),
        )


class ControlModeEngine:
    """Execute tmux commands over one persistent ``tmux -C`` connection.

    Parameters
    ----------
    tmux_bin : str or None
        The tmux binary; resolved via :func:`shutil.which` when ``None``.
    server_args : Sequence[str]
        Connection flags inserted before ``-C``.
    timeout : float
        Seconds to wait for a batch of result blocks before raising.

    Notes
    -----
    The connection is opened lazily on first use. Call :meth:`close` (or use the
    engine as a context manager) to tear it down.
    """

    def __init__(
        self,
        tmux_bin: str | None = None,
        *,
        server_args: Sequence[str] = (),
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.tmux_bin = tmux_bin
        self.server_args = tuple(server_args)
        self.timeout = timeout
        self._lock = threading.Lock()
        self._parser = ControlModeParser()
        self._proc: subprocess.Popen[bytes] | None = None
        self._selector: selectors.DefaultSelector | None = None

    def tmux_version(self) -> str | None:
        """Report the connected server's tmux version (``tmux -V``).

        Implements
        :class:`~libtmux.experimental.engines.base.SupportsTmuxVersion` so
        version-gated operations render correctly over control mode; in-memory
        engines omit it and resolution assumes latest.
        """
        try:
            return str(get_version(self.tmux_bin))
        except exc.LibTmuxException:
            return None

    def run(self, request: CommandRequest) -> CommandResult:
        """Execute one tmux command over the control connection."""
        return self.run_batch([request])[0]

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Pipeline a batch of commands; one result per request.

        A ``;``-folded request runs as several tmux commands, so its blocks are
        grouped (by ``;``-count) and merged into one result.
        """
        if not requests:
            return []
        rendered = [tuple(req.args) for req in requests]
        counts = [command_count(argv) for argv in rendered]
        with self._lock:
            self._ensure_started()
            # Discard any unsolicited blocks (hook-triggered commands) left
            # buffered from earlier activity, so they cannot be mis-attributed
            # to this batch's commands.
            self._drain_unsolicited()
            payload = b"".join(
                (render_control_line(argv) + "\n").encode() for argv in rendered
            )
            self._write(payload)
            blocks = self._read_blocks(sum(counts))
        results: list[CommandResult] = []
        index = 0
        for argv, count in zip(rendered, counts, strict=True):
            results.append(_merge_blocks(blocks[index : index + count], argv))
            index += count
        return results

    def close(self) -> None:
        """Tear down the control-mode subprocess (lock-guarded)."""
        with self._lock:
            proc = self._proc
            selector = self._selector
            self._proc = None
            self._selector = None
            self._parser = ControlModeParser()
            if selector is not None:
                with contextlib.suppress(Exception):
                    selector.close()
            if proc is None:
                return
            if proc.stdin is not None and not proc.stdin.closed:
                with contextlib.suppress(OSError):
                    proc.stdin.close()
            if not _wait_for_exit(proc, _GRACEFUL_EXIT_TIMEOUT):
                with contextlib.suppress(OSError):
                    proc.terminate()
                if not _wait_for_exit(proc, _TERMINATE_TIMEOUT):
                    with contextlib.suppress(OSError):
                        proc.kill()
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        proc.wait(timeout=_TERMINATE_TIMEOUT)

    def __enter__(self) -> ControlModeEngine:
        """Return this engine."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Tear down the connection on context exit."""
        self.close()

    def _ensure_started(self) -> None:
        if self._proc is not None:
            if self._proc.poll() is not None:
                msg = f"tmux -C exited with code {self._proc.returncode}"
                raise ControlModeError(msg)
            return
        tmux_bin = self.tmux_bin or shutil.which("tmux")
        if tmux_bin is None:
            raise exc.TmuxCommandNotFound
        cmd = [tmux_bin, *self.server_args, "-C"]
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except FileNotFoundError:
            raise exc.TmuxCommandNotFound from None
        if proc.stdin is None or proc.stdout is None or proc.stderr is None:
            with contextlib.suppress(OSError):
                proc.kill()
            msg = "tmux -C subprocess pipes are unavailable"
            raise ControlModeError(msg)
        os.set_blocking(proc.stdout.fileno(), False)
        os.set_blocking(proc.stderr.fileno(), False)
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ, "stdout")
        selector.register(proc.stderr, selectors.EVENT_READ, "stderr")
        self._proc = proc
        self._selector = selector
        self._consume_startup()
        self._reap_own_session()

    def _consume_startup(self) -> None:
        """Read and discard tmux's startup ACK block before any command.

        Consuming it up front (instead of skipping the first block heuristically
        at read time) means the startup block can never be conflated with a
        command's result block.
        """
        deadline = time.monotonic() + _STARTUP_TIMEOUT
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            if self._proc is not None and self._proc.poll() is not None:
                return
            self._pump(remaining)
            if self._parser.blocks():  # startup ACK seen and discarded
                self._parser.notifications()
                return
            self._parser.notifications()

    def _reap_own_session(self) -> None:
        """Mark this control client's throwaway session ``destroy-unattached``.

        A bare ``tmux -C`` connect implies ``new-session``, so set
        ``destroy-unattached on`` on the *current* session (the phantom; no
        ``-t``/``-g``, scoped to exactly it) right after connect. tmux reaps it
        the moment the client disconnects, so control mode leaves no throwaway
        sessions. Its result block is read and discarded here -- before any user
        command -- so it cannot desync the next command. Best-effort.
        """
        proc = self._proc
        if proc is None or proc.stdin is None:
            return
        argv = ("set-option", "destroy-unattached", "on")
        with contextlib.suppress(OSError, BrokenPipeError, ControlModeError):
            self._write((render_control_line(argv) + "\n").encode())
            self._read_blocks(command_count(argv))

    def _drain_unsolicited(self) -> None:
        """Discard any blocks/notifications already buffered (non-blocking)."""
        selector = self._selector
        if selector is None:
            return
        while selector.select(0):
            self._pump(0)
        self._parser.blocks()
        self._parser.notifications()

    def _pump(self, timeout: float) -> None:
        """Wait up to *timeout* for output and feed it to the parser."""
        selector = self._selector
        if selector is None:
            return
        for key, _events in selector.select(timeout):
            if key.data == "stdout":
                self._read_stdout()
            elif key.data == "stderr":
                self._read_stderr()

    def _write(self, payload: bytes) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            msg = "control-mode subprocess is not connected"
            raise ControlModeError(msg)
        try:
            proc.stdin.write(payload)
            proc.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            msg = f"tmux control-mode write failed: {error}"
            raise ControlModeError(msg) from error

    def _read_blocks(self, count: int) -> list[ControlModeBlock]:
        proc = self._proc
        selector = self._selector
        if proc is None or selector is None:
            msg = "control-mode subprocess is not connected"
            raise ControlModeError(msg)
        blocks: list[ControlModeBlock] = []
        deadline = time.monotonic() + self.timeout
        while len(blocks) < count:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                msg = (
                    f"tmux control-mode timed out after {self.timeout}s "
                    f"waiting for {count} result blocks"
                )
                raise ControlModeError(msg)
            ready = selector.select(min(remaining, 0.1))
            if not ready:
                if proc.poll() is not None:
                    msg = f"tmux -C exited with code {proc.returncode}"
                    raise ControlModeError(msg)
                continue
            for key, _events in ready:
                if key.data == "stdout":
                    self._read_stdout()
                elif key.data == "stderr":
                    self._read_stderr()
            for block in self._parser.blocks():
                # Skip unsolicited blocks (hook-triggered commands carry flags 0);
                # only solicited command blocks (flags 1) belong to this batch.
                if block.flags == 1 and len(blocks) < count:
                    blocks.append(block)
            self._parser.notifications()  # sync engine ignores notifications
        return blocks

    def _read_stdout(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            chunk = os.read(proc.stdout.fileno(), _READ_CHUNK)
        except BlockingIOError:
            return
        except OSError as error:
            msg = f"tmux control-mode stdout read failed: {error}"
            raise ControlModeError(msg) from error
        if not chunk:
            msg = "tmux -C closed stdout"
            raise ControlModeError(msg)
        self._parser.feed(chunk)

    def _read_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            chunk = os.read(proc.stderr.fileno(), _READ_CHUNK)
        except (BlockingIOError, OSError):
            return
        if chunk:
            logger.debug(
                "tmux control-mode stderr",
                extra={"tmux_stderr": [chunk.decode(errors="replace")]},
            )

    @classmethod
    def for_server(cls, server: t.Any, **kwargs: t.Any) -> ControlModeEngine:
        """Build a control-mode engine bound to a live server's socket."""
        server_args: list[str] = []
        if getattr(server, "socket_name", None):
            server_args.append(f"-L{server.socket_name}")
        if getattr(server, "socket_path", None):
            server_args.append(f"-S{server.socket_path}")
        if getattr(server, "config_file", None):
            server_args.append(f"-f{server.config_file}")
        colors = getattr(server, "colors", None)
        if colors == 256:
            server_args.append("-2")
        elif colors == 88:
            server_args.append("-8")
        return cls(
            tmux_bin=getattr(server, "tmux_bin", None),
            server_args=server_args,
            **kwargs,
        )


def _wait_for_exit(proc: subprocess.Popen[bytes], timeout: float) -> bool:
    """Wait up to *timeout* for the process to exit; return whether it did."""
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return True


def _parse_guard(line: bytes, prefix: bytes) -> tuple[int | None, int | None]:
    """Parse a ``%begin``/``%end``/``%error`` guard's number and flags."""
    parts = line[len(prefix) :].split()
    if len(parts) < _GUARD_MIN_PARTS:
        return (None, None)
    try:
        return (int(parts[1]), int(parts[2]))
    except ValueError:
        return (None, None)


def _matches_pending_close(line: bytes, pending_number: int) -> bool:
    """Whether *line* closes the pending block numbered *pending_number*."""
    for prefix in (_END_PREFIX, _ERROR_PREFIX):
        if line.startswith(prefix):
            number, _flags = _parse_guard(line, prefix)
            return number == pending_number
    return False


def command_count(argv: tuple[str, ...]) -> int:
    """How many tmux commands a rendered argv runs (bare ``;`` separators + 1)."""
    return sum(1 for token in argv if token == ";") + 1


def _merge_blocks(
    blocks: Sequence[ControlModeBlock],
    argv: tuple[str, ...],
) -> CommandResult:
    """Merge one request's blocks (one per ``;``-folded sub-command) into a result.

    A ``;``-folded line runs as several tmux commands, each emitting its own
    block; stdout/stderr are concatenated and the result fails if any sub-command
    errored, matching the subprocess engine's view of one ``;`` chain process.
    """
    cmd = ("tmux", "-C", *argv)
    stdout: list[str] = []
    stderr: list[str] = []
    returncode = 0
    for block in blocks:
        lines = tuple(line.decode(errors="replace") for line in block.body)
        if block.is_error:
            stderr.extend(lines)
            returncode = returncode or 1
        else:
            stdout.extend(lines)
    return CommandResult(
        cmd=cmd,
        stdout=_trim(tuple(stdout)),
        stderr=_trim(tuple(stderr)),
        returncode=returncode,
    )


def _trim(lines: tuple[str, ...]) -> tuple[str, ...]:
    """Drop trailing blank lines."""
    trimmed = list(lines)
    while trimmed and not trimmed[-1].strip():
        trimmed.pop()
    return tuple(trimmed)
