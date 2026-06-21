"""The ``set-buffer`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class SetBuffer(Operation[AckResult]):
    """Set the contents of a paste buffer (``set-buffer``).

    Parameters
    ----------
    data : str
        The buffer contents.
    buffer_name : str or None
        The buffer to set (``-b``); tmux picks a name when omitted.
    append : bool
        Append to the buffer instead of replacing it (``-a``).

    Examples
    --------
    >>> SetBuffer(data="hello").render()
    ('set-buffer', 'hello')
    >>> SetBuffer(buffer_name="b0", data="hi").render()
    ('set-buffer', '-b', 'b0', 'hi')
    """

    kind = "set_buffer"
    command = "set-buffer"
    scope = "server"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects()

    data: str
    buffer_name: str | None = None
    append: bool = False

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the buffer flags and data."""
        out: list[str] = []
        if self.append:
            out.append("-a")
        if self.buffer_name is not None:
            out.extend(("-b", self.buffer_name))
        out.append(self.data)
        return tuple(out)
