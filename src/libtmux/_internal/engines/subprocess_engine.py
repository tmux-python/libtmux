"""Subprocess engine for libtmux."""

from __future__ import annotations

import logging
import shutil
import subprocess
import typing as t

from libtmux import exc
from libtmux._internal.engines.base import CommandResult, Engine, ExitStatus

logger = logging.getLogger(__name__)


class SubprocessEngine(Engine):
    """Engine that runs tmux commands via subprocess."""

    def run_result(
        self,
        cmd: str,
        cmd_args: t.Sequence[str | int] | None = None,
        server_args: t.Sequence[str | int] | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        """Run a tmux command using ``subprocess.Popen``."""
        tmux_bin = shutil.which("tmux")
        if not tmux_bin:
            raise exc.TmuxCommandNotFound

        full_cmd: list[str | int] = [tmux_bin]
        if server_args:
            full_cmd += list(server_args)
        full_cmd.append(cmd)
        if cmd_args:
            full_cmd += list(cmd_args)

        full_cmd_str = [str(c) for c in full_cmd]

        try:
            process = subprocess.Popen(
                full_cmd_str,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="backslashreplace",
            )
            stdout_str, stderr_str = process.communicate(timeout=timeout)
            returncode = process.returncode
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            msg = "tmux subprocess timed out"
            raise exc.SubprocessTimeout(msg) from None
        except Exception:
            logger.exception(f"Exception for {subprocess.list2cmdline(full_cmd_str)}")
            raise

        stdout_split = stdout_str.split("\n")
        while stdout_split and stdout_split[-1] == "":
            stdout_split.pop()

        stderr_split = stderr_str.split("\n")
        stderr = list(filter(None, stderr_split))

        if "has-session" in full_cmd_str and len(stderr) and not stdout_split:
            stdout = [stderr[0]]
        else:
            stdout = stdout_split

        logger.debug(
            "self.stdout for {cmd}: {stdout}".format(
                cmd=" ".join(full_cmd_str),
                stdout=stdout,
            ),
        )

        exit_status = ExitStatus.OK if returncode == 0 else ExitStatus.ERROR

        return CommandResult(
            argv=full_cmd_str,
            stdout=stdout,
            stderr=stderr,
            exit_status=exit_status,
        )
