"""The ``swap-pane`` operation (dual-target)."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class SwapPane(Operation[AckResult]):
    """Swap two panes (``swap-pane``).

    ``target`` is the destination pane (``-t``); ``src_target`` is the source
    pane (``-s``). With *up*/*down* and no source, swap with the adjacent pane.

    Parameters
    ----------
    detach : bool
        Do not change the active pane (``-d``).
    up, down : bool
        Swap with the pane above (``-U``) / below (``-D``).
    zoom : bool
        Keep the window zoomed (``-Z``).

    Examples
    --------
    >>> from libtmux.experimental.ops._types import PaneId
    >>> SwapPane(target=PaneId("%1"), src_target=PaneId("%2")).render()
    ('swap-pane', '-t', '%1', '-s', '%2')
    >>> SwapPane(target=PaneId("%1"), down=True, detach=True).render()
    ('swap-pane', '-t', '%1', '-d', '-D')
    """

    kind = "swap_pane"
    command = "swap-pane"
    scope = "pane"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects()

    detach: bool = False
    up: bool = False
    down: bool = False
    zoom: bool = False

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the swap flags and ``-s`` source."""
        out: list[str] = []
        if self.detach:
            out.append("-d")
        if self.up:
            out.append("-U")
        if self.down:
            out.append("-D")
        if self.zoom:
            out.append("-Z")
        out.extend(self.src_args())
        return tuple(out)
