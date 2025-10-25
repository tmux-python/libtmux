"""Subprocess-based command execution engine."""

from __future__ import annotations

import typing as t

if t.TYPE_CHECKING:
    from libtmux.common import tmux_cmd


class SubprocessCommandRunner:
    """Command runner that uses subprocess to execute tmux binary.

    This is the default command runner and wraps the existing tmux_cmd
    implementation for backward compatibility.

    Examples
    --------
    >>> runner = SubprocessCommandRunner()
    >>> result = runner.run("-V")
    >>> assert hasattr(result, 'stdout')
    >>> assert hasattr(result, 'stderr')
    >>> assert hasattr(result, 'returncode')
    """

    def run(self, *args: str) -> tmux_cmd:
        """Execute tmux command via subprocess.

        Parameters
        ----------
        *args : str
            Arguments to pass to tmux binary

        Returns
        -------
        tmux_cmd
            Command result with stdout, stderr, returncode
        """
        from libtmux.common import tmux_cmd

        return tmux_cmd(*args)
