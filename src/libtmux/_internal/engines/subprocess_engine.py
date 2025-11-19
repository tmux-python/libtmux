"""Subprocess engine for libtmux."""

from __future__ import annotations

import logging
import shutil
import subprocess
import typing as t

from libtmux import exc
from libtmux._internal.engines.base import Engine
from libtmux.common import tmux_cmd

logger = logging.getLogger(__name__)


class SubprocessEngine(Engine):
    """Engine that runs tmux commands via subprocess."""

    def run(
        self,
        cmd: str,
        cmd_args: t.Sequence[str | int] | None = None,
        server_args: t.Sequence[str | int] | None = None,
    ) -> tmux_cmd:
        """Run a tmux command using subprocess.Popen."""
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
            stdout_str, stderr_str = process.communicate()
            returncode = process.returncode
        except Exception:
            logger.exception(f"Exception for {subprocess.list2cmdline(full_cmd_str)}")
            raise

        stdout_split = stdout_str.split("\n")
        # remove trailing newlines from stdout
        while stdout_split and stdout_split[-1] == "":
            stdout_split.pop()

        stderr_split = stderr_str.split("\n")
        stderr = list(filter(None, stderr_split))  # filter empty values

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

        return tmux_cmd(
            cmd=full_cmd_str,
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
        )
