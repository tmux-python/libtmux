"""Control Mode engine for libtmux."""

from __future__ import annotations

import logging
import shlex
import shutil
import subprocess
import threading
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

    def __del__(self) -> None:
        """Cleanup the process on destruction."""
        self.close()

    def _start_process(self, server_args: t.Sequence[str | int] | None) -> None:
        """Start the tmux control mode process."""
        tmux_bin = shutil.which("tmux")
        if not tmux_bin:
            raise exc.TmuxCommandNotFound

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

        # Consume startup command output with the same timeout used for commands.
        assert self.process.stdout is not None

        def bootstrap_reader() -> None:
            assert self.process is not None
            assert self.process.stdout is not None
            while True:
                line = self.process.stdout.readline()
                if not line:
                    logger.warning("Control Mode process exited immediately")
                    break
                if line.startswith("%end") or line.startswith("%error"):
                    break

        if self.command_timeout is None:
            bootstrap_reader()
        else:
            bootstrap_thread = threading.Thread(target=bootstrap_reader, daemon=True)
            bootstrap_thread.start()
            bootstrap_thread.join(timeout=self.command_timeout)
            if bootstrap_thread.is_alive():
                logger.error("Control Mode bootstrap command timed out")
                self.close()
                msg = "tmux control mode command timed out"
                raise exc.ControlModeTimeout(msg)

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
            assert self.process.stdout is not None

            # Construct the command line
            # We use shlex.join for correct shell-like quoting, required by tmux control
            # mode.
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

            # Read response
            stdout_lines: list[str] = []
            stderr_lines: list[str] = []
            returncode = 0

            def reader() -> None:
                nonlocal returncode, stdout_lines, stderr_lines
                assert self.process is not None
                assert self.process.stdout is not None
                while True:
                    line = self.process.stdout.readline()
                    if not line:
                        # EOF
                        logger.error("Unexpected EOF from Control Mode process")
                        returncode = 1
                        break

                    line = line.rstrip("\n")

                    if line.startswith("%begin"):
                        # %begin time id flags
                        parts = line.split()
                        if len(parts) > 3:
                            flags = int(parts[3])
                            if flags & 1:
                                returncode = 1
                        continue
                    elif line.startswith("%end"):
                        # %end time id flags
                        parts = line.split()
                        if len(parts) > 3:
                            flags = int(parts[3])
                            if flags & 1:
                                returncode = 1
                        break
                    elif line.startswith("%error"):
                        returncode = 1
                        stderr_lines = stdout_lines
                        stdout_lines = []
                        break
                    elif line.startswith("%"):
                        logger.debug("Control Mode Notification: %s", line)
                        continue
                    else:
                        stdout_lines.append(line)

            reader_exc: list[BaseException] = []

            def wrapped_reader() -> None:
                try:
                    reader()
                except BaseException as read_exc:  # pragma: no cover - defensive
                    reader_exc.append(read_exc)

            effective_timeout = timeout if timeout is not None else self.command_timeout
            if effective_timeout is None:
                wrapped_reader()
            else:
                reader_thread = threading.Thread(target=wrapped_reader, daemon=True)
                reader_thread.start()
                reader_thread.join(timeout=effective_timeout)
                if reader_thread.is_alive():
                    logger.error(
                        "Control Mode command timed out waiting for response: %s",
                        command_line,
                    )
                    self.close()
                    msg = "tmux control mode command timed out"
                    raise exc.ControlModeTimeout(msg)
                if reader_exc:
                    raise reader_exc[0]

            # Tmux usually puts error message in stdout (captured above) for %error
            # But we moved it to stderr_lines if %error occurred.

            # If we detected failure via flags but got %end, treat stdout as potentially
            # containing info?
            # For now, keep stdout as is.

            # Mimic subprocess.communicate output structure
            return tmux_cmd(
                cmd=[cmd] + (list(map(str, cmd_args)) if cmd_args else []),
                stdout=stdout_lines,
                stderr=stderr_lines,
                returncode=returncode,
            )
