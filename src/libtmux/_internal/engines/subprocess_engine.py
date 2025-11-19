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

    def run(self, *args: t.Any) -> tmux_cmd:
        """Run a tmux command using subprocess.Popen."""
        tmux_bin = shutil.which("tmux")
        if not tmux_bin:
            raise exc.TmuxCommandNotFound

        cmd = [tmux_bin]
        cmd += args  # add the command arguments to cmd
        cmd = [str(c) for c in cmd]

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="backslashreplace",
            )
            stdout_str, stderr_str = process.communicate()
            returncode = process.returncode
        except Exception:
            logger.exception(f"Exception for {subprocess.list2cmdline(cmd)}")
            raise

        stdout_split = stdout_str.split("\n")
        # remove trailing newlines from stdout
        while stdout_split and stdout_split[-1] == "":
            stdout_split.pop()

        stderr_split = stderr_str.split("\n")
        stderr = list(filter(None, stderr_split))  # filter empty values

        if "has-session" in cmd and len(stderr) and not stdout_split:
            stdout = [stderr[0]]
        else:
            stdout = stdout_split

        logger.debug(
            "self.stdout for {cmd}: {stdout}".format(
                cmd=" ".join(cmd),
                stdout=stdout,
            ),
        )

        return tmux_cmd(
            cmd=cmd,
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
        )
