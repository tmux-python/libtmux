"""Constant variables for libtmux."""

from __future__ import annotations

import enum


class ResizeAdjustmentDirection(enum.Enum):
    """Used for *adjustment* in ``resize_window``, ``resize_pane``."""

    Up = "UP"
    Down = "DOWN"
    Left = "LEFT"
    Right = "RIGHT"


RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP: dict[ResizeAdjustmentDirection, str] = {
    ResizeAdjustmentDirection.Up: "-U",
    ResizeAdjustmentDirection.Down: "-D",
    ResizeAdjustmentDirection.Left: "-L",
    ResizeAdjustmentDirection.Right: "-R",
}


class WindowDirection(enum.Enum):
    """Used for *adjustment* in :meth:`Session.new_window()`."""

    Before = "BEFORE"
    After = "AFTER"


WINDOW_DIRECTION_FLAG_MAP: dict[WindowDirection, str] = {
    WindowDirection.Before: "-b",
    WindowDirection.After: "-a",
}


class PaneDirection(enum.Enum):
    """Used for *adjustment* in :meth:`Pane.split()`."""

    Above = "ABOVE"
    Below = "BELOW"  # default with no args
    Right = "RIGHT"
    Left = "LEFT"


PANE_DIRECTION_FLAG_MAP: dict[PaneDirection, list[str]] = {
    # -v is assumed, but for explicitness it is passed
    PaneDirection.Above: ["-v", "-b"],
    PaneDirection.Below: ["-v"],
    PaneDirection.Right: ["-h"],
    PaneDirection.Left: ["-h", "-b"],
}
