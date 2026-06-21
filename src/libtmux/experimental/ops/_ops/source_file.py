"""The ``source-file`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class SourceFile(Operation[AckResult]):
    """Execute tmux commands from a file (``source-file``).

    Parameters
    ----------
    path : str
        Path to the file to source.
    quiet : bool
        Suppress errors for missing files (``-q``).
    verbose : bool
        Show the parsed commands (``-v``).
    no_exec : bool
        Parse but do not execute (``-n``).

    Examples
    --------
    >>> SourceFile(path="~/.tmux.conf").render()
    ('source-file', '~/.tmux.conf')
    """

    kind = "source_file"
    command = "source-file"
    scope = "server"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects()

    path: str
    quiet: bool = False
    verbose: bool = False
    no_exec: bool = False

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the source-file flags and path."""
        out: list[str] = []
        if self.no_exec:
            out.append("-n")
        if self.quiet:
            out.append("-q")
        if self.verbose:
            out.append("-v")
        out.append(self.path)
        return tuple(out)
