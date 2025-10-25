"""Control-mode backed tmux engine."""

from __future__ import annotations

import logging
import shutil
import subprocess

from libtmux import exc
from libtmux.engines.base import CommandResult, TmuxEngine

logger = logging.getLogger(__name__)


def _decode_control_payload(payload: str) -> str:
    """Decode tmux control mode payload sequences."""
    if not payload:
        return ""
    # Control mode escapes mirror C-style escapes. ``unicode_escape`` handles both
    # simple escapes and octal sequences (e.g. ``\012``).
    try:
        return bytes(payload, "utf-8").decode("unicode_escape")
    except Exception:  # pragma: no cover - defensive, should not happen
        logger.debug("Failed to decode control payload %r", payload, exc_info=True)
        return payload


class ControlModeEngine(TmuxEngine):
    """Execute tmux commands via control mode (``tmux -C``)."""

    def run(self, *args: str | int) -> CommandResult:
        """Execute a tmux command using control mode and return structured output."""
        tmux_bin = shutil.which("tmux")
        if tmux_bin is None:
            raise exc.TmuxCommandNotFound

        cmd: list[str] = [tmux_bin, "-C"]
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

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        for line in stdout.splitlines():
            if line.startswith("%output"):
                parts = line.split(" ", 4)
                payload = parts[4] if len(parts) >= 5 else ""
                stdout_lines.append(_decode_control_payload(payload))
            elif line.startswith("%error"):
                # ``%error time client flags code message``
                parts = line.split(" ", 5)
                payload = parts[5] if len(parts) >= 6 else ""
                stderr_lines.append(_decode_control_payload(payload))
            elif line.startswith(("%begin", "%end", "%exit")):
                continue
            else:
                # Unexpected line: keep behaviour predictable by surfacing it
                stdout_lines.append(line)

        # Combine regular stderr with parsed control errors
        stderr_lines.extend(line for line in stderr.splitlines() if line)

        logger.debug("control-mode stdout for %s: %s", " ".join(cmd), stdout_lines)

        return CommandResult(
            cmd=cmd,
            stdout=stdout_lines,
            stderr=stderr_lines,
            returncode=returncode,
            process=None,
        )


__all__ = ["ControlModeEngine"]
