"""Control mode protocol parser."""

from __future__ import annotations

from typing import IO

from .result import ControlModeResult


class ProtocolParser:
    r"""Parser for tmux control mode protocol.

    Handles %begin/%end/%error blocks and notifications.

    The tmux control mode protocol format:
    - Commands produce output blocks
    - Blocks start with %begin and end with %end or %error
    - Format: %begin timestamp cmd_num flags
    - Notifications (%session-changed, etc.) can appear between blocks

    Examples
    --------
    >>> import io
    >>> stdout = io.StringIO(
    ...     "%begin 1234 1 0\n"
    ...     "session1\n"
    ...     "%end 1234 1 0\n"
    ... )
    >>> parser = ProtocolParser(stdout)
    >>> result = parser.parse_response(["list-sessions"])
    >>> result.stdout
    ['session1']
    >>> result.returncode
    0
    """

    def __init__(self, stdout: IO[str]) -> None:
        self.stdout = stdout
        self.notifications: list[str] = []

    def parse_response(self, cmd: list[str]) -> ControlModeResult:
        """Parse a single command response.

        Parameters
        ----------
        cmd : list[str]
            The command that was executed (for result.cmd)

        Returns
        -------
        ControlModeResult
            Parsed result with stdout, stderr, returncode

        Raises
        ------
        ConnectionError
            If connection closes unexpectedly
        ProtocolError
            If protocol format is unexpected
        """
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        returncode = 0

        # State machine
        in_response = False

        while True:
            line = self.stdout.readline()
            if not line:  # EOF
                msg = "Control mode connection closed unexpectedly"
                raise ConnectionError(msg)

            line = line.rstrip("\n")

            # Parse line type
            if line.startswith("%begin"):
                # %begin timestamp cmd_num flags
                in_response = True
                continue

            elif line.startswith("%end"):
                # Success - response complete
                return ControlModeResult(stdout_lines, stderr_lines, returncode, cmd)

            elif line.startswith("%error"):
                # Error - command failed
                returncode = 1
                # Note: error details are in stdout_lines already
                return ControlModeResult(stdout_lines, stderr_lines, returncode, cmd)

            elif line.startswith("%"):
                # Notification - queue for future processing
                self.notifications.append(line)
                # Don't break - keep reading for our response
                continue

            else:
                # Regular output line
                if in_response:
                    stdout_lines.append(line)
                # else: orphaned line before %begin (should not happen in practice)


class ProtocolError(Exception):
    """Raised when control mode protocol is violated."""

    pass
