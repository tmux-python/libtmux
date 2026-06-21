"""Control-mode runner for experimental chain commands.

This module keeps the control-mode surface scoped to
``libtmux._experimental.chain``. It borrows the persistent ``tmux -C`` +
batched-stdin shape from the protocol-engines experiments without installing a
general engine registry into this branch.

Note
----
This is an **experimental** API, not covered by the project's versioning policy.
It may change or be removed between any releases without notice.
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import os
import selectors
import shlex
import shutil
import subprocess
import threading
import time
import typing as t

from libtmux import exc
from libtmux._experimental.chain.ir import Arg, CommandCall, CommandChain

if t.TYPE_CHECKING:
    import types
    from collections.abc import Sequence

    from libtmux.server import Server

logger = logging.getLogger(__name__)

_BEGIN_PREFIX = b"%begin "
_END_PREFIX = b"%end "
_ERROR_PREFIX = b"%error "
_READ_CHUNK = 65536
_DEFAULT_TIMEOUT = 30.0
_GRACEFUL_EXIT_TIMEOUT = 0.5
_TERMINATE_TIMEOUT = 1.0
_NOTIFICATION_PREFIXES = (
    b"%extended-output ",
    b"%output ",
    b"%pause ",
    b"%continue ",
    b"%session-changed ",
    b"%client-session-changed ",
    b"%session-renamed ",
    b"%sessions-changed",
    b"%session-window-changed ",
    b"%window-add ",
    b"%window-close ",
    b"%window-renamed ",
    b"%window-pane-changed ",
    b"%pane-mode-changed ",
    b"%unlinked-window-add ",
    b"%unlinked-window-close ",
    b"%unlinked-window-renamed ",
    b"%paste-buffer-changed ",
    b"%paste-buffer-deleted ",
    b"%client-detached ",
    b"%subscription-changed ",
    b"%exit",
    b"%message ",
)


class ControlModeError(exc.LibTmuxException):
    """The experimental control-mode runner failed."""


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
    """I/O-free parser for the subset of control mode needed by chains."""

    __slots__ = ("_blocks", "_buffer", "_pending")

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._blocks: list[ControlModeBlock] = []
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

    def _handle_line(self, line: bytes) -> None:
        if self._pending is not None:
            if line.startswith(_END_PREFIX) or line.startswith(_ERROR_PREFIX):
                self._close_block(line)
                return
            if any(line.startswith(prefix) for prefix in _NOTIFICATION_PREFIXES):
                return
            self._pending.body.append(line)
            return

        if line.startswith(_BEGIN_PREFIX):
            self._open_block(line)

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

        prefix = _ERROR_PREFIX if line.startswith(_ERROR_PREFIX) else _END_PREFIX
        number, _flags = _parse_guard(line, prefix)
        if number is not None and number != pending.number:
            logger.warning(
                "control-mode close guard number mismatch",
                extra={
                    "tmux_cm_block_id": pending.number,
                    "tmux_cm_close_id": number,
                },
            )

        self._blocks.append(
            ControlModeBlock(
                number=pending.number,
                flags=pending.flags,
                is_error=line.startswith(_ERROR_PREFIX),
                body=tuple(pending.body),
            ),
        )


@dataclasses.dataclass(slots=True)
class ControlModeResult:
    """Result shape returned by :class:`ControlModeRunner`."""

    stdout: list[str]
    stderr: list[str]
    returncode: int


class ControlModeRunner:
    """Persistent ``tmux -C`` runner for experimental command chains.

    The runner batches independent command lines over one control-mode
    connection. Unlike a native ``;`` chain, each line returns its own
    ``%begin``/``%end`` block, so callers can keep per-command stdout and
    return codes while avoiding per-command subprocess startup.
    """

    def __init__(
        self,
        server: Server,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.server = server
        self.timeout = timeout
        self._lock = threading.Lock()
        self._parser = ControlModeParser()
        self._proc: subprocess.Popen[bytes] | None = None
        self._selector: selectors.DefaultSelector | None = None
        self._startup_ack_pending = True

    def cmd(
        self,
        cmd: str,
        *args: Arg,
        target: str | int | None = None,
    ) -> ControlModeResult:
        """Dispatch one command through the persistent control client."""
        call = CommandCall(name=cmd, args=tuple(args), target=target)
        return self.run_calls([call])[0]

    def run_calls(self, calls: Sequence[CommandCall]) -> list[ControlModeResult]:
        """Dispatch command calls as one control-mode batch."""
        return self.run_argvs([call.argv() for call in calls])

    def run_chain(self, chain: CommandChain) -> list[ControlModeResult]:
        """Dispatch a ``CommandChain`` with one result per contained call."""
        return self.run_calls(chain.calls)

    def run_argvs(self, argvs: Sequence[Sequence[Arg]]) -> list[ControlModeResult]:
        """Dispatch rendered tmux argv rows as one control-mode batch."""
        if not argvs:
            return []

        rendered = [tuple(str(arg) for arg in argv) for argv in argvs]
        with self._lock:
            self._ensure_started()
            payload = b"".join(
                (shlex.join(argv) + "\n").encode("utf-8") for argv in rendered
            )
            self._write(payload)
            blocks = self._read_blocks(len(rendered))

        return [_result_from_block(block) for block in blocks]

    def close(self) -> None:
        """Close the control-mode subprocess.

        Acquires the run lock so teardown never closes the selector out from
        under an in-flight :meth:`run_argvs` reading on another thread.
        """
        with self._lock:
            proc = self._proc
            selector = self._selector
            self._proc = None
            self._selector = None
            self._parser = ControlModeParser()
            self._startup_ack_pending = True

            if selector is not None:
                with contextlib.suppress(Exception):
                    selector.close()
            if proc is None:
                return

            if proc.stdin is not None and not proc.stdin.closed:
                with contextlib.suppress(OSError):
                    proc.stdin.write(b"\n")
                    proc.stdin.flush()
            if not _wait_for_exit(proc, _GRACEFUL_EXIT_TIMEOUT):
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

    def __enter__(self) -> ControlModeRunner:
        """Return this runner."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Close the control-mode subprocess."""
        self.close()

    def _ensure_started(self) -> None:
        if self._proc is not None:
            if self._proc.poll() is not None:
                msg = f"tmux -C exited with code {self._proc.returncode}"
                raise ControlModeError(msg)
            return

        tmux_bin = self.server.tmux_bin or shutil.which("tmux")
        if tmux_bin is None:
            raise exc.TmuxCommandNotFound

        cmd = [tmux_bin, *self._server_args(), "-C"]
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
        self._startup_ack_pending = True

    def _server_args(self) -> list[str]:
        args: list[str] = []
        if self.server.socket_name:
            args.extend(("-L", str(self.server.socket_name)))
        if self.server.socket_path:
            args.extend(("-S", str(self.server.socket_path)))
        if self.server.config_file:
            args.extend(("-f", str(self.server.config_file)))
        if self.server.colors == 256:
            args.append("-2")
        elif self.server.colors == 88:
            args.append("-8")
        elif self.server.colors is not None:
            raise exc.UnknownColorOption
        return args

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
                    "tmux control-mode timed out after "
                    f"{self.timeout}s waiting for {count} result blocks"
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
                if self._startup_ack_pending:
                    self._startup_ack_pending = False
                    if block.flags == 0:
                        continue
                blocks.append(block)
                if len(blocks) == count:
                    break

        return blocks

    def _read_stdout(self) -> None:
        proc = self._proc
        assert proc is not None
        assert proc.stdout is not None
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
        assert proc is not None
        assert proc.stderr is not None
        try:
            chunk = os.read(proc.stderr.fileno(), _READ_CHUNK)
        except (BlockingIOError, OSError):
            return
        if chunk:
            logger.debug(
                "tmux control-mode stderr",
                extra={"tmux_stderr": [chunk.decode("utf-8", errors="replace")]},
            )


def _parse_guard(
    line: bytes,
    prefix: bytes,
) -> tuple[int | None, int | None]:
    rest = line[len(prefix) :]
    parts = rest.split()
    if len(parts) < 3:
        return (None, None)
    try:
        number = int(parts[1])
        flags = int(parts[2])
    except ValueError:
        return (None, None)
    return (number, flags)


def _result_from_block(block: ControlModeBlock) -> ControlModeResult:
    lines = [line.decode("utf-8", errors="replace") for line in block.body]
    if block.is_error:
        return ControlModeResult(stdout=[], stderr=_trim_lines(lines), returncode=1)
    return ControlModeResult(stdout=_trim_lines(lines), stderr=[], returncode=0)


def _trim_lines(lines: list[str]) -> list[str]:
    trimmed = list(lines)
    while trimmed and not trimmed[-1].strip():
        trimmed.pop()
    return trimmed


def _wait_for_exit(proc: subprocess.Popen[bytes], timeout: float) -> bool:
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return True


__all__ = [
    "ControlModeBlock",
    "ControlModeError",
    "ControlModeParser",
    "ControlModeResult",
    "ControlModeRunner",
]
