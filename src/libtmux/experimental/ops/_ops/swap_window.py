"""The ``swap-window`` operation (dual-target)."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class SwapWindow(Operation[AckResult]):
    """Swap two windows (``swap-window``).

    ``target`` is the destination (``-t``); ``src_target`` is the source
    window (``-s``).

    Parameters
    ----------
    detach : bool
        Do not change the active window (``-d``).

    Examples
    --------
    >>> from libtmux.experimental.ops._types import WindowId
    >>> SwapWindow(target=WindowId("@1"), src_target=WindowId("@2")).render()
    ('swap-window', '-t', '@1', '-s', '@2')
    """

    kind = "swap_window"
    command = "swap-window"
    scope = "window"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects()

    detach: bool = False

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the optional ``-d`` flag and ``-s`` source."""
        out: list[str] = []
        if self.detach:
            out.append("-d")
        out.extend(self.src_args())
        return tuple(out)
