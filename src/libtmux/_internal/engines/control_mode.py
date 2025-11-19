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

    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._server_args: t.Sequence[str | int] | None = None

    def close(self) -> None:
        """Terminate the tmux control mode process."""
        if self.process:
            self.process.terminate()
            self.process.wait()
            self.process = None

    def __del__(self) -> None:
        """Cleanup the process on destruction."""
        self.close()

    def _start_process(self, server_args: t.Sequence[str | int] | None) -> None:
        """Start the tmux control mode process."""
        tmux_bin = shutil.which("tmux")
        if not tmux_bin:
            raise exc.TmuxCommandNotFound

        cmd = [tmux_bin]
        if server_args:
            cmd.extend(str(a) for a in server_args)
        cmd.append("-C")
        cmd.extend(["new-session", "-A", "-s", "libtmux_control_mode"])

        logger.debug(f"Starting Control Mode process: {cmd}")
        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=0,  # Unbuffered
            errors="backslashreplace",
        )
        self._server_args = server_args

        # Consume startup command output
        assert self.process.stdout is not None
        while True:
            line = self.process.stdout.readline()
            if not line:
                # EOF immediately?
                logger.warning("Control Mode process exited immediately")
                break
            if line.startswith("%end") or line.startswith("%error"):
                break

    def run(
        self,
        cmd: str,
        cmd_args: t.Sequence[str | int] | None = None,
        server_args: t.Sequence[str | int] | None = None,
    ) -> tmux_cmd:
        """Run a tmux command via Control Mode."""
        with self._lock:
            if self.process is None:
                self._start_process(server_args)
            elif server_args != self._server_args:
                # If server_args changed, we might need a new process.
                # For now, just warn or restart. Restarting is safer.
                logger.warning(
                    "Server args changed, restarting Control Mode process. "
                    f"Old: {self._server_args}, New: {server_args}"
                )
                self.close()
                self._start_process(server_args)

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

            logger.debug(f"Sending to Control Mode: {command_line}")
            try:
                self.process.stdin.write(command_line + "\n")
                self.process.stdin.flush()
            except BrokenPipeError:
                # Process died?
                logger.exception("Control Mode process died, restarting...")
                self.close()
                self._start_process(server_args)
                assert self.process is not None
                assert self.process.stdin is not None
                assert self.process.stdout is not None
                self.process.stdin.write(command_line + "\n")
                self.process.stdin.flush()

            # Read response
            stdout_lines: list[str] = []
            stderr_lines: list[str] = []
            returncode = 0

            while True:
                line = self.process.stdout.readline()
                if not line:
                    # EOF
                    logger.error("Unexpected EOF from Control Mode process")
                    returncode = 1
                    break

                line = line.rstrip("\n")

                if line.startswith("%begin"):
                    # Start of response
                    # %begin time id flags
                    parts = line.split()
                    if len(parts) > 3:
                        flags = int(parts[3])
                        if flags & 1:
                            returncode = 1
                    continue
                elif line.startswith("%end"):
                    # End of success response
                    # %end time id flags
                    parts = line.split()
                    if len(parts) > 3:
                        flags = int(parts[3])
                        if flags & 1:
                            returncode = 1
                    break
                elif line.startswith("%error"):
                    # End of error response
                    returncode = 1
                    # Captured lines are the error message
                    stderr_lines = stdout_lines
                    stdout_lines = []
                    break
                elif line.startswith("%"):
                    # Notification (ignore for now)
                    logger.debug(f"Control Mode Notification: {line}")
                    continue
                else:
                    stdout_lines.append(line)

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
