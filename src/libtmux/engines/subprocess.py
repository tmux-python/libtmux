"""Subprocess-backed tmux engine."""

from __future__ import annotations

import logging
import shutil
import subprocess

from libtmux import exc
from libtmux.engines.base import CommandResult, TmuxEngine

logger = logging.getLogger(__name__)


class SubprocessEngine(TmuxEngine):
    """Execute tmux commands via the tmux CLI binary."""

    def run(self, *args: str | int) -> CommandResult:
        """Execute a tmux command via subprocess and return structured output."""
        tmux_bin = shutil.which("tmux")
        if tmux_bin is None:
            raise exc.TmuxCommandNotFound

        cmd: list[str] = [tmux_bin]
        cmd.extend(str(value) for value in args)

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="backslashreplace",
            )
            stdout, stderr = process.communicate()
            returncode = process.returncode
        except Exception:
            logger.exception("Exception for %s", subprocess.list2cmdline(cmd))
            raise

        stdout_lines = stdout.split("\n")
        while stdout_lines and stdout_lines[-1] == "":
            stdout_lines.pop()

        stderr_lines = [line for line in stderr.split("\n") if line]

        if "has-session" in cmd and stderr_lines and not stdout_lines:
            stdout_lines = [stderr_lines[0]]

        logger.debug(
            "self.stdout for %s: %s",
            " ".join(cmd),
            stdout_lines,
        )

        return CommandResult(
            cmd=cmd,
            stdout=stdout_lines,
            stderr=stderr_lines,
            returncode=returncode,
            process=process,
        )


__all__ = ["SubprocessEngine"]
