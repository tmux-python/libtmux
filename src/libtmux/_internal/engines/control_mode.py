"""Control Mode engine for libtmux."""

from __future__ import annotations

import contextlib
import logging
import queue
import shlex
import shutil
import subprocess
import threading
import time
import typing as t

from libtmux import exc
from libtmux._internal.engines.base import Engine
from libtmux.common import tmux_cmd

logger = logging.getLogger(__name__)


class ControlModeEngine(Engine):
    """Engine that runs tmux commands via a persistent Control Mode process."""

    def __init__(self, command_timeout: float | None = 10.0) -> None:
        self.process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._server_args: tuple[str | int, ...] | None = None
        self.command_timeout = command_timeout
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=1024)
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self.tmux_bin: str | None = None

    def close(self) -> None:
        """Terminate the tmux control mode process."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process = None
            self._server_args = None
            # Unblock any waiters
            with contextlib.suppress(queue.Full):
                self._queue.put_nowait(None)

    def __del__(self) -> None:
        """Cleanup the process on destruction."""
        self.close()

    def _reader(self, process: subprocess.Popen[str]) -> None:
        """Background thread to read stdout and push to queue."""
        assert process.stdout is not None
        while True:
            try:
                line = process.stdout.readline()
            except (ValueError, OSError):
                break

            if not line:
                # EOF
                with contextlib.suppress(queue.Full):
                    self._queue.put_nowait(None)
                break

            if line.startswith("%") and not line.startswith(
                ("%begin", "%end", "%error"),
            ):
                logger.debug("Control Mode Notification: %s", line.rstrip("\n"))
                continue

            try:
                self._queue.put(line, timeout=1)
            except queue.Full:
                logger.warning("Control Mode queue full; dropping line")

    def _drain_stderr(self, process: subprocess.Popen[str]) -> None:
        """Continuously drain stderr to prevent child blocking."""
        if process.stderr is None:
            return
        for err_line in process.stderr:
            logger.debug("Control Mode stderr: %s", err_line.rstrip("\n"))

    def _start_process(self, server_args: t.Sequence[str | int] | None) -> None:
        """Start the tmux control mode process."""
        tmux_bin = shutil.which("tmux")
        if not tmux_bin:
            raise exc.TmuxCommandNotFound
        self.tmux_bin = tmux_bin

        normalized_args: tuple[str | int, ...] = tuple(server_args or ())

        cmd = [tmux_bin]
        if normalized_args:
            cmd.extend(str(a) for a in normalized_args)
        cmd.append("-C")
        cmd.extend(["new-session", "-A", "-s", "libtmux_control_mode"])

        logger.debug("Starting Control Mode process: %s", cmd)
        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=0,  # Unbuffered
            errors="backslashreplace",
        )
        self._server_args = normalized_args

        # reset queues from prior runs
        while not self._queue.empty():
            self._queue.get_nowait()

        # Start IO threads
        self._reader_thread = threading.Thread(
            target=self._reader,
            args=(self.process,),
            daemon=True,
        )
        self._reader_thread.start()

        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            args=(self.process,),
            daemon=True,
        )
        self._stderr_thread.start()

        # Consume startup command output with the same timeout used for commands.
        try:
            self._read_response(cmd="new-session", timeout=self.command_timeout)
        except exc.ControlModeTimeout:
            logger.exception("Control Mode bootstrap command timed out")
            self.close()
            raise

    def _read_response(self, cmd: str, timeout: float | None) -> tmux_cmd:
        """Read response from the queue."""
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        returncode = 0

        start_time = time.monotonic()

        while True:
            if timeout is None:
                remaining: float | None = None
            else:
                elapsed = time.monotonic() - start_time
                remaining = timeout - elapsed
                if remaining <= 0:
                    msg = "tmux control mode command timed out"
                    raise exc.ControlModeTimeout(msg)

            try:
                line = self._queue.get(timeout=remaining)
            except queue.Empty:
                msg = "tmux control mode command timed out"
                raise exc.ControlModeTimeout(msg) from None

            if line is None:
                logger.error("Unexpected EOF from Control Mode process")
                returncode = 1
                break

            line = line.rstrip("\n")

            if line.startswith("%begin"):
                parts = line.split()
                if len(parts) > 3:
                    flags = int(parts[3])
                    if flags & 1:
                        returncode = 1
                continue
            if line.startswith("%end"):
                parts = line.split()
                if len(parts) > 3:
                    flags = int(parts[3])
                    if flags & 1:
                        returncode = 1
                break
            if line.startswith("%error"):
                returncode = 1
                stderr_lines = stdout_lines
                stdout_lines = []
                break

            stdout_lines.append(line)

        if cmd == "has-session" and stderr_lines and not stdout_lines:
            stdout_lines = [stderr_lines[0]]

        return tmux_cmd(
            cmd=[],
            stdout=stdout_lines,
            stderr=stderr_lines,
            returncode=returncode,
        )

    def run(
        self,
        cmd: str,
        cmd_args: t.Sequence[str | int] | None = None,
        server_args: t.Sequence[str | int] | None = None,
        timeout: float | None = None,
    ) -> tmux_cmd:
        """Run a tmux command via Control Mode."""
        with self._lock:
            incoming_server_args = tuple(server_args or ())

            if self.process is None:
                self._start_process(incoming_server_args)
            elif incoming_server_args != self._server_args:
                # If server_args changed, we might need a new process.
                # For now, just warn or restart. Restarting is safer.
                logger.warning(
                    "Server args changed; restarting Control Mode process. "
                    "Old: %s, New: %s",
                    self._server_args,
                    incoming_server_args,
                )
                self.close()
                self._start_process(incoming_server_args)

            assert self.process is not None
            assert self.process.stdin is not None
            # Construct the command line
            full_args = [cmd]
            if cmd_args:
                full_args.extend(str(a) for a in cmd_args)

            command_line = shlex.join(full_args)

            logger.debug("Sending to Control Mode: %s", command_line)
            try:
                self.process.stdin.write(command_line + "\n")
                self.process.stdin.flush()
            except BrokenPipeError:
                # Process died?
                logger.exception("Control Mode process died, restarting...")
                self.close()
                self._start_process(incoming_server_args)
                assert self.process is not None
                assert self.process.stdin is not None
                assert self.process.stdout is not None
                self.process.stdin.write(command_line + "\n")
                self.process.stdin.flush()

            effective_timeout = timeout if timeout is not None else self.command_timeout

            try:
                result = self._read_response(cmd=cmd, timeout=effective_timeout)
            except exc.ControlModeTimeout:
                self.close()
                raise

            full_cmd = [self.tmux_bin or "tmux"]
            if incoming_server_args:
                full_cmd.extend(str(x) for x in incoming_server_args)
            full_cmd.append(cmd)
            if cmd_args:
                full_cmd.extend(str(x) for x in cmd_args)
            result.cmd = full_cmd
            return result
