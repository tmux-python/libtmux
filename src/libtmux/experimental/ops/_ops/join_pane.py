"""The ``join-pane`` operation (dual-target)."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class JoinPane(Operation[AckResult]):
    """Join a source pane into a destination window/pane (``join-pane``).

    ``target`` is the destination (``-t``); ``src_target`` is the pane to move
    (``-s``). The inverse of :class:`BreakPane`.

    Parameters
    ----------
    horizontal : bool
        Split the destination left/right (``-h``) instead of top/bottom (``-v``).
    detach : bool
        Do not switch to the destination window (``-d``).
    full_size : bool
        Span the full window width/height (``-f``).
    size : int or None
        Size of the joined pane (``-l``).
    before : bool
        Place the pane before the destination (``-b``).

    Examples
    --------
    >>> from libtmux.experimental.ops._types import PaneId, WindowId
    >>> JoinPane(target=WindowId("@1"), src_target=PaneId("%2")).render()
    ('join-pane', '-t', '@1', '-v', '-d', '-s', '%2')
    """

    kind = "join_pane"
    command = "join-pane"
    scope = "pane"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects()

    horizontal: bool = False
    detach: bool = True
    full_size: bool = False
    size: int | None = None
    before: bool = False

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the join flags and ``-s`` source."""
        out: list[str] = ["-h" if self.horizontal else "-v"]
        if self.detach:
            out.append("-d")
        if self.full_size:
            out.append("-f")
        if self.size is not None:
            out.append(f"-l{self.size}")
        if self.before:
            out.append("-b")
        out.extend(self.src_args())
        return tuple(out)
