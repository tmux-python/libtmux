"""The ``paste-buffer`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class PasteBuffer(Operation[AckResult]):
    """Paste a buffer into a pane (``paste-buffer``).

    ``target`` is the destination pane.

    Parameters
    ----------
    buffer_name : str or None
        The buffer to paste (``-b``); the most recent when omitted.
    delete : bool
        Delete the buffer after pasting (``-d``).
    bracket : bool
        Use bracketed paste mode (``-p``).
    no_replace : bool
        Do no separator replacement: keep linefeeds (LF) instead of
        converting them to the default carriage-return separator (``-r``).
    separator : str or None
        Separator inserted between lines (``-s``).

    Examples
    --------
    >>> from libtmux.experimental.ops._types import PaneId
    >>> PasteBuffer(target=PaneId("%1")).render()
    ('paste-buffer', '-t', '%1')
    >>> PasteBuffer(target=PaneId("%1"), delete=True).render()
    ('paste-buffer', '-t', '%1', '-d')
    """

    kind = "paste_buffer"
    command = "paste-buffer"
    scope = "pane"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects(writes_input=True)

    buffer_name: str | None = None
    delete: bool = False
    bracket: bool = False
    no_replace: bool = False
    separator: str | None = None

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the paste flags and buffer name."""
        out: list[str] = []
        if self.delete:
            out.append("-d")
        if self.bracket:
            out.append("-p")
        if self.no_replace:
            out.append("-r")
        if self.buffer_name is not None:
            out.extend(("-b", self.buffer_name))
        if self.separator is not None:
            out.extend(("-s", self.separator))
        return tuple(out)
