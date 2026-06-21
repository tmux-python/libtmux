"""The ``clear-history`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class ClearHistory(Operation[AckResult]):
    """Clear a pane's scrollback history (``clear-history``).

    Examples
    --------
    >>> from libtmux.experimental.ops._types import PaneId
    >>> ClearHistory(target=PaneId("%1")).render()
    ('clear-history', '-t', '%1')
    """

    kind = "clear_history"
    command = "clear-history"
    scope = "pane"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects(idempotent=True)
