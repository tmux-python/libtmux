"""Async transport built on tmux control mode."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
from collections import deque
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from libtmux.errors import (
    CommandError,
    OperationTimeout,
    TmuxCommandNotFound,
    TransportClosed,
)

from ._types import CommandResult, TmuxEvent, Transport

_LOGGER = logging.getLogger(__name__)


def _resolve_tmux_executable(executable: str | None = None) -> str:
    if executable:
        return executable
    tmux_bin = shutil.which("tmux")
    if not tmux_bin:
        message = "tmux executable not found in PATH"
        raise TmuxCommandNotFound(message)
    return tmux_bin


@dataclass
class _PendingCommand:
    future: asyncio.Future[CommandResult]
    argv: Sequence[str]
    stdout: list[str]
    stderr: list[str]
    returncode: int | None = None


class ControlModeTransport(Transport):
    """Transport that communicates with tmux via control mode."""

    def __init__(
        self,
        *,
        socket_name: str | None = None,
        socket_path: str | None = None,
        config_file: str | None = None,
        colors: int | None = None,
        tmux_executable: str | None = None,
        max_event_queue: int = 256,
        event_policy: str = "drop_oldest",
        env: dict[str, str] | None = None,
    ) -> None:
        self._socket_name = socket_name
        self._socket_path = socket_path
        self._config_file = config_file
        self._colors = colors
        self._tmux_executable = tmux_executable
        self._env_override = env

        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._cmd_counter = 0
        self._pending: dict[int, _PendingCommand] = {}
        self._events: asyncio.Queue[TmuxEvent] = asyncio.Queue(maxsize=max_event_queue)
        self._event_policy = event_policy
        self._closed = True
        self._last_frame: str | None = None
        self._stderr_buffer: deque[str] = deque(maxlen=20)
        self._logger = _LOGGER.getChild("control")
        self._stdin_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._process is not None:
            if self._process.returncode is None:
                return
            await self.stop()

        tmux_bin = _resolve_tmux_executable(self._tmux_executable)
        argv = [tmux_bin, "-C"]

        if self._socket_name:
            argv.extend(["-L", self._socket_name])
        if self._socket_path:
            argv.extend(["-S", self._socket_path])
        if self._config_file:
            argv.extend(["-f", self._config_file])
        if self._colors:
            if self._colors == 256:
                argv.append("-2")
            elif self._colors == 88:
                argv.append("-8")

        env = os.environ.copy()
        if self._env_override:
            env.update(self._env_override)

        self._logger.debug("starting tmux control-mode process", extra={"argv": argv})
        self._process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._closed = False
        self._cmd_counter = 0
        self._pending.clear()
        self._drain_events()
        reader_task = asyncio.create_task(self._reader(), name="tmux-control-reader")
        self._reader_task = reader_task

    async def stop(self) -> None:
        process = self._process
        self._closed = True
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
            self._reader_task = None

        if process is None:
            return

        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

        self._process = None
        self._fail_pending(TransportClosed("transport stopped"))
        self._drain_events()

    async def run(self, argv: Sequence[str], *, timeout: float | None) -> CommandResult:
        if self._process is None or self._process.stdin is None:
            message = "transport not started"
            raise TransportClosed(message)

        self._cmd_counter += 1
        cmd_id = self._cmd_counter
        loop = asyncio.get_running_loop()
        future: asyncio.Future[CommandResult] = loop.create_future()
        pending = _PendingCommand(future=future, argv=argv, stdout=[], stderr=[])
        self._pending[cmd_id] = pending

        line = " ".join(str(arg) for arg in argv)
        payload = f"{line}\n".encode()

        async with self._stdin_lock:
            try:
                self._process.stdin.write(payload)
                await self._process.stdin.drain()
            except BrokenPipeError as exc:  # pragma: no cover - defensive
                self._pending.pop(cmd_id, None)
                message = "tmux control-mode stdin closed"
                raise TransportClosed(message) from exc

        try:
            if timeout is None:
                result = await future
            else:
                async with asyncio.timeout(timeout):
                    result = await future
        except asyncio.TimeoutError as exc:
            self._pending.pop(cmd_id, None)
            message = f"tmux command timed out: {tuple(argv)!r}"
            raise OperationTimeout(message) from exc
        except Exception:
            self._pending.pop(cmd_id, None)
            raise

        return result

    def events(self) -> AsyncIterator[TmuxEvent]:
        async def iterator() -> AsyncIterator[TmuxEvent]:
            while True:
                event = await self._events.get()
                yield event

        return iterator()

    async def _reader(self) -> None:
        assert self._process is not None
        stdout = self._process.stdout
        stderr = self._process.stderr
        assert stdout is not None and stderr is not None

        async def read_stderr() -> None:
            while True:
                chunk = await stderr.readline()
                if not chunk:
                    break
                text = chunk.decode(errors="backslashreplace").rstrip("\n")
                self._stderr_buffer.append(text)
                self._logger.debug("stderr", extra={"line": text})

        stderr_task = asyncio.create_task(read_stderr())

        try:
            while True:
                line_bytes = await stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode(errors="backslashreplace").rstrip("\n")
                self._last_frame = line
                try:
                    self._handle_frame(line)
                except Exception as exc:  # pragma: no cover - defensive
                    self._logger.exception(
                        "error parsing tmux frame", extra={"line": line}
                    )
                    self._fail_pending(exc)
                    break
        finally:
            stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stderr_task
            self._handle_process_exit()

    def _handle_process_exit(self) -> None:
        exit_code = self._process.returncode if self._process else None
        message = "tmux control-mode process exited"
        self._logger.debug(message, extra={"returncode": exit_code})
        self._closed = True
        self._process = None
        error = TransportClosed(
            f"tmux control-mode process exited with code {exit_code!r}"
        )
        if self._last_frame:
            error.add_note(f"last_frame={self._last_frame}")
        for stderr_line in self._stderr_buffer:
            error.add_note(f"stderr: {stderr_line}")
        self._fail_pending(error)

    def _fail_pending(self, exc: Exception) -> None:
        for pending in list(self._pending.values()):
            if not pending.future.done():
                pending.future.set_exception(exc)
        self._pending.clear()

    def _handle_frame(self, line: str) -> None:
        if not line.startswith("%"):
            self._publish_event(
                {
                    "kind": "output",
                    "pane_id": None,
                    "data": line,
                    "raw": line,
                }
            )
            return

        parts = line.split(" ", 2)
        frame = parts[0]

        if frame == "%begin" and len(parts) >= 2:
            cmd_id = int(parts[1])
            pending = self._pending.get(cmd_id)
            if pending is None:
                loop = asyncio.get_running_loop()
                pending = _PendingCommand(
                    future=loop.create_future(),
                    argv=(),
                    stdout=[],
                    stderr=[],
                )
                self._pending[cmd_id] = pending
            return

        if frame == "%end" and len(parts) >= 3:
            cmd_id = int(parts[1])
            exit_status = int(parts[2])
            pending = self._pending.pop(cmd_id, None)
            if pending is None:
                return
            stdout = "\n".join(pending.stdout)
            stderr = "\n".join(pending.stderr)
            result: CommandResult = {
                "stdout": stdout,
                "stderr": stderr,
                "returncode": exit_status,
                "cmd_id": cmd_id,
            }
            if exit_status != 0:
                error = CommandError(
                    stdout=stdout,
                    stderr=stderr,
                    returncode=exit_status,
                )
                if not pending.future.done():
                    pending.future.set_exception(error)
            else:
                if not pending.future.done():
                    pending.future.set_result(result)
            return

        if frame == "%error" and len(parts) >= 2:
            cmd_id = int(parts[1])
            message = parts[2] if len(parts) == 3 else ""
            pending = self._pending.pop(cmd_id, None)
            stdout = "\n".join(pending.stdout) if pending else ""
            stderr = message
            error = CommandError(stdout=stdout, stderr=stderr, returncode=1)
            if pending and not pending.future.done():
                pending.future.set_exception(error)
            else:
                self._publish_event(
                    {
                        "kind": "error",
                        "pane_id": None,
                        "data": message,
                        "raw": line,
                    }
                )
            return

        if frame in {"%output", "%stderr"} and len(parts) >= 2:
            cmd_and_rest = parts[1:]
            if len(cmd_and_rest) == 1:
                cmd_id = int(cmd_and_rest[0])
                target = None
                data = ""
            else:
                cmd_id_str, rest = cmd_and_rest[0], parts[2] if len(parts) == 3 else ""
                target_and_data = rest.split(" ", 1)
                target = target_and_data[0] if target_and_data else ""
                data = target_and_data[1] if len(target_and_data) > 1 else ""
                cmd_id = int(cmd_id_str)
            if cmd_id == -1:
                self._publish_event(
                    {
                        "kind": frame.lstrip("%"),
                        "pane_id": target,
                        "data": data,
                        "raw": line,
                    }
                )
            else:
                pending = self._pending.get(cmd_id)
                if pending:
                    if frame == "%stderr":
                        pending.stderr.append(data)
                    else:
                        pending.stdout.append(data)
            return

        # Any other control mode frame becomes a generic event.
        self._publish_event(
            {
                "kind": frame.lstrip("%"),
                "pane_id": None,
                "data": parts[1] if len(parts) > 1 else None,
                "raw": line,
            }
        )

    def _publish_event(self, event: TmuxEvent) -> None:
        try:
            self._events.put_nowait(event)
        except asyncio.QueueFull:
            if self._event_policy == "drop_oldest":
                with contextlib.suppress(asyncio.QueueEmpty):
                    self._events.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    self._events.put_nowait(event)
            else:
                raise

    def _drain_events(self) -> None:
        while not self._events.empty():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._events.get_nowait()


__all__ = ["ControlModeTransport"]
