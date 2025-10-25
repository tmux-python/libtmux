"""Command runner protocols for tmux execution engines."""

from __future__ import annotations

import typing as t
from typing import Protocol

if t.TYPE_CHECKING:
    pass


class CommandResult(Protocol):
    """Protocol for command execution results.

    Any object conforming to this protocol can be returned by a CommandRunner.
    The existing tmux_cmd class automatically conforms to this protocol.

    Attributes
    ----------
    stdout : list[str]
        Command standard output, split by lines
    stderr : list[str]
        Command standard error, split by lines
    returncode : int
        Command return code
    cmd : list[str]
        The command that was executed (for debugging)
    """

    @property
    def stdout(self) -> list[str]:
        """Command standard output, split by lines."""
        ...

    @property
    def stderr(self) -> list[str]:
        """Command standard error, split by lines."""
        ...

    @property
    def returncode(self) -> int:
        """Command return code."""
        ...

    @property
    def cmd(self) -> list[str]:
        """The command that was executed (for debugging)."""
        ...


class CommandRunner(Protocol):
    """Protocol for tmux command execution engines.

    Implementations must provide a run() method that executes tmux commands
    and returns a CommandResult.

    Examples
    --------
    >>> from libtmux._internal.engines import SubprocessCommandRunner
    >>> runner = SubprocessCommandRunner()
    >>> result = runner.run("-V")
    >>> assert hasattr(result, 'stdout')
    >>> assert hasattr(result, 'stderr')
    >>> assert hasattr(result, 'returncode')
    """

    def run(self, *args: str) -> CommandResult:
        """Execute a tmux command.

        Parameters
        ----------
        *args : str
            Command arguments to pass to tmux binary

        Returns
        -------
        CommandResult
            Object with stdout, stderr, returncode, cmd attributes
        """
        ...
