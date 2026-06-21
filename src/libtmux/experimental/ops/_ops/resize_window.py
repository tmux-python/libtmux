"""The ``resize-window`` operation."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class ResizeWindow(Operation[AckResult]):
    """Resize a window (``resize-window``).

    Parameters
    ----------
    direction : {"L", "R", "U", "D"} or None
        Resize toward a side (``-L``/``-R``/``-U``/``-D``).
    adjustment : int or None
        Cells to adjust by when *direction* is set.
    width, height : int or None
        Absolute width (``-x``) / height (``-y``) in cells.

    Examples
    --------
    >>> from libtmux.experimental.ops._types import WindowId
    >>> ResizeWindow(target=WindowId("@1"), width=100).render()
    ('resize-window', '-t', '@1', '-x100')
    """

    kind = "resize_window"
    command = "resize-window"
    scope = "window"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects(mutates_layout=True)

    direction: t.Literal["L", "R", "U", "D"] | None = None
    adjustment: int | None = None
    width: int | None = None
    height: int | None = None

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the resize flags."""
        out: list[str] = []
        if self.direction is not None:
            out.append(f"-{self.direction}")
            if self.adjustment is not None:
                out.append(str(self.adjustment))
        if self.width is not None:
            out.append(f"-x{self.width}")
        if self.height is not None:
            out.append(f"-y{self.height}")
        return tuple(out)
