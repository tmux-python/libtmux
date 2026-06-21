"""The ``rotate-window`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class RotateWindow(Operation[AckResult]):
    """Rotate the panes in a window (``rotate-window``).

    Parameters
    ----------
    up, down : bool
        Rotate upward (``-U``) or downward (``-D``).
    zoom : bool
        Keep the window zoomed (``-Z``).

    Examples
    --------
    >>> from libtmux.experimental.ops._types import WindowId
    >>> RotateWindow(target=WindowId("@1")).render()
    ('rotate-window', '-t', '@1')
    >>> RotateWindow(target=WindowId("@1"), up=True).render()
    ('rotate-window', '-t', '@1', '-U')
    """

    kind = "rotate_window"
    command = "rotate-window"
    scope = "window"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects(mutates_layout=True)

    up: bool = False
    down: bool = False
    zoom: bool = False

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the rotate flags."""
        out: list[str] = []
        if self.up:
            out.append("-U")
        if self.down:
            out.append("-D")
        if self.zoom:
            out.append("-Z")
        return tuple(out)
