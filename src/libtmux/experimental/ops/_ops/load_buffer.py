"""The ``load-buffer`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class LoadBuffer(Operation[AckResult]):
    """Load a paste buffer from a file (``load-buffer``).

    Parameters
    ----------
    path : str
        The file to load (``-`` for stdin).
    buffer_name : str or None
        The buffer to load into (``-b``).

    Examples
    --------
    >>> LoadBuffer(path="/tmp/x").render()
    ('load-buffer', '/tmp/x')
    >>> LoadBuffer(buffer_name="b0", path="/tmp/x").render()
    ('load-buffer', '-b', 'b0', '/tmp/x')
    """

    kind = "load_buffer"
    command = "load-buffer"
    scope = "server"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects()

    path: str
    buffer_name: str | None = None

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the optional buffer name and path."""
        out: list[str] = []
        if self.buffer_name is not None:
            out.extend(("-b", self.buffer_name))
        out.append(self.path)
        return tuple(out)
