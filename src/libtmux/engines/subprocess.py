"""Subprocess-backed tmux engine."""

from __future__ import annotations

import logging
import pathlib
import shlex
import shutil
import subprocess

from libtmux import exc
from libtmux.engines.base import CommandRequest, CommandResult
from libtmux.engines.registry import register_engine

logger = logging.getLogger(__name__)


class SubprocessEngine:
    """Execute tmux commands via the tmux CLI binary."""

    def __init__(self, tmux_bin: str | pathlib.Path | None = None) -> None:
        self.tmux_bin = str(tmux_bin) if tmux_bin is not None else None

    def run(self, request: CommandRequest) -> CommandResult:
        """Execute a tmux command via subprocess and return structured output."""
        tmux_bin = request.tmux_bin or self.tmux_bin or shutil.which("tmux")
        if tmux_bin is None:
            raise exc.TmuxCommandNotFound

        cmd = [tmux_bin, *request.args]

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
        except FileNotFoundError:
            raise exc.TmuxCommandNotFound from None
        except Exception:
            logger.exception(
                "tmux subprocess failed",
                extra={"tmux_cmd": shlex.join(cmd)},
            )
            raise

        stdout_lines = stdout.split("\n")
        while stdout_lines and stdout_lines[-1] == "":
            stdout_lines.pop()

        stderr_lines = [line for line in stderr.split("\n") if line]

        if "has-session" in cmd and stderr_lines and not stdout_lines:
            stdout_lines = [stderr_lines[0]]

        return CommandResult(
            cmd=cmd,
            stdout=stdout_lines,
            stderr=stderr_lines,
            returncode=returncode,
            process=process,
        )


register_engine("subprocess", SubprocessEngine)
