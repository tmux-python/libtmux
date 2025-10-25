"""Result type for control mode command execution."""

from __future__ import annotations


class ControlModeResult:
    """Result from control mode execution.

    Duck-types as tmux_cmd for backward compatibility.
    Has identical interface: stdout, stderr, returncode, cmd.

    Attributes
    ----------
    stdout : list[str]
        Command standard output, split by lines
    stderr : list[str]
        Command standard error, split by lines
    returncode : int
        Command return code (0 = success, 1 = error)
    cmd : list[str]
        The command that was executed (for debugging)

    Examples
    --------
    >>> result = ControlModeResult(
    ...     stdout=["session1", "session2"],
    ...     stderr=[],
    ...     returncode=0,
    ...     cmd=["tmux", "-C", "list-sessions"]
    ... )
    >>> result.stdout
    ['session1', 'session2']
    >>> result.returncode
    0
    >>> bool(result.stderr)
    False
    """

    __slots__ = ("cmd", "returncode", "stderr", "stdout")

    def __init__(
        self,
        stdout: list[str],
        stderr: list[str],
        returncode: int,
        cmd: list[str],
    ) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.cmd = cmd

    def __repr__(self) -> str:
        return (
            f"ControlModeResult(returncode={self.returncode}, "
            f"stdout_lines={len(self.stdout)}, stderr_lines={len(self.stderr)})"
        )
