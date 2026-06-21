"""The ``save-buffer`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class SaveBuffer(Operation[AckResult]):
    """Save a paste buffer to a file (``save-buffer``).

    Parameters
    ----------
    path : str
        The file to write (``-`` for stdout).
    buffer_name : str or None
        The buffer to save (``-b``).
    append : bool
        Append to the file instead of overwriting it (``-a``).

    Examples
    --------
    >>> SaveBuffer(path="/tmp/x").render()
    ('save-buffer', '/tmp/x')
    >>> SaveBuffer(buffer_name="b0", path="/tmp/x", append=True).render()
    ('save-buffer', '-a', '-b', 'b0', '/tmp/x')
    """

    kind = "save_buffer"
    command = "save-buffer"
    scope = "server"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects(read_only=True)

    path: str
    buffer_name: str | None = None
    append: bool = False

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the flags, optional buffer name, and path."""
        out: list[str] = []
        if self.append:
            out.append("-a")
        if self.buffer_name is not None:
            out.extend(("-b", self.buffer_name))
        out.append(self.path)
        return tuple(out)
