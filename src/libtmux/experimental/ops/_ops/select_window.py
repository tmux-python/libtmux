"""The ``select-window`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class SelectWindow(Operation[AckResult]):
    """Make a window active (``select-window``).

    Examples
    --------
    >>> from libtmux.experimental.ops._types import WindowId
    >>> SelectWindow(target=WindowId("@1")).render()
    ('select-window', '-t', '@1')
    """

    kind = "select_window"
    command = "select-window"
    scope = "window"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects(idempotent=True)
