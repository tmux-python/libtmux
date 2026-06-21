"""The ``select-layout`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class SelectLayout(Operation[AckResult]):
    """Apply a layout to a window.

    Parameters
    ----------
    layout : str or None
        A named layout (``even-horizontal``, ``main-vertical``, ...) or a custom
        layout string. ``None`` re-applies the current layout.

    Examples
    --------
    >>> from libtmux.experimental.ops._types import WindowId
    >>> SelectLayout(target=WindowId("@1"), layout="main-vertical").render()
    ('select-layout', '-t', '@1', 'main-vertical')
    >>> SelectLayout(target=WindowId("@1")).render()
    ('select-layout', '-t', '@1')
    """

    kind = "select_layout"
    command = "select-layout"
    scope = "window"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects(idempotent=True, mutates_layout=True)

    layout: str | None = None

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the optional layout argument."""
        return (self.layout,) if self.layout is not None else ()
