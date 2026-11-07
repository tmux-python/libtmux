"""The ``last-pane`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class LastPane(Operation[AckResult]):
    """Select the previously active pane in a window (``last-pane``).

    ``target`` is the window whose last pane to select.

    Examples
    --------
    >>> from libtmux.experimental.ops._types import WindowId
    >>> LastPane(target=WindowId("@1")).render()
    ('last-pane', '-t', '@1')
    """

    kind = "last_pane"
    command = "last-pane"
    scope = "window"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects(idempotent=True)
