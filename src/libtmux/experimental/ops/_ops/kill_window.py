"""The ``kill-window`` operation (no output -- an acknowledgement)."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class KillWindow(Operation[AckResult]):
    """Kill a window. Destructive; produces no output (:class:`AckResult`).

    Parameters
    ----------
    others : bool
        Kill all windows *except* the target (``-a``) instead of the target.

    Examples
    --------
    >>> from libtmux.experimental.ops._types import WindowId
    >>> KillWindow(target=WindowId("@1")).render()
    ('kill-window', '-t', '@1')
    >>> KillWindow(target=WindowId("@1"), others=True).render()
    ('kill-window', '-t', '@1', '-a')
    """

    kind = "kill_window"
    command = "kill-window"
    scope = "window"
    result_cls = AckResult
    safety = "destructive"
    effects = Effects(destructive=True)

    others: bool = False

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the optional ``-a`` flag."""
        return ("-a",) if self.others else ()
