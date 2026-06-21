"""The ``pipe-pane`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class PipePane(Operation[AckResult]):
    """Pipe a pane's output to a shell command (``pipe-pane``).

    Parameters
    ----------
    command_line : str or None
        Shell command to pipe to. Omit to stop an existing pipe.
    stdin : bool
        Connect the pane's input to the command (``-I``).
    stdout : bool
        Connect the pane's output to the command (``-O``).
    toggle : bool
        Only open the pipe if no pipe is already open on the pane (``-o``).

    Examples
    --------
    >>> from libtmux.experimental.ops._types import PaneId
    >>> PipePane(target=PaneId("%1"), command_line="cat >>/tmp/log").render()
    ('pipe-pane', '-t', '%1', 'cat >>/tmp/log')
    >>> PipePane(target=PaneId("%1")).render()
    ('pipe-pane', '-t', '%1')
    """

    kind = "pipe_pane"
    command = "pipe-pane"
    scope = "pane"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects(reads_output=True)

    command_line: str | None = None
    stdin: bool = False
    stdout: bool = False
    toggle: bool = False

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the pipe flags and command."""
        out: list[str] = []
        if self.stdin:
            out.append("-I")
        if self.stdout:
            out.append("-O")
        if self.toggle:
            out.append("-o")
        if self.command_line is not None:
            out.append(self.command_line)
        return tuple(out)
