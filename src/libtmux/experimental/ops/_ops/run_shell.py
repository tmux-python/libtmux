"""The ``run-shell`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class RunShell(Operation[AckResult]):
    """Run a shell command via tmux (``run-shell``).

    Parameters
    ----------
    command_line : str or None
        The shell command to run.
    background : bool
        Run in the background (``-b``).
    delay : int or None
        Delay in seconds before running (``-d``).

    Examples
    --------
    >>> RunShell(command_line="echo hi").render()
    ('run-shell', 'echo hi')
    """

    kind = "run_shell"
    command = "run-shell"
    scope = "server"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects()

    command_line: str | None = None
    background: bool = False
    delay: int | None = None

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the run-shell flags and command."""
        out: list[str] = []
        if self.background:
            out.append("-b")
        if self.delay is not None:
            out.extend(("-d", str(self.delay)))
        if self.command_line is not None:
            out.append(self.command_line)
        return tuple(out)
