"""The ``kill-pane`` operation (no output -- an acknowledgement)."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class KillPane(Operation[AckResult]):
    """Kill a pane. Destructive; produces no output (:class:`AckResult`).

    Parameters
    ----------
    others : bool
        Kill all panes *except* the target (``-a``) instead of the target.

    Examples
    --------
    >>> from libtmux.experimental.ops._types import PaneId
    >>> KillPane(target=PaneId("%1")).render()
    ('kill-pane', '-t', '%1')
    """

    kind = "kill_pane"
    command = "kill-pane"
    scope = "pane"
    result_cls = AckResult
    safety = "destructive"
    effects = Effects(destructive=True)

    others: bool = False

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the optional ``-a`` flag."""
        return ("-a",) if self.others else ()
