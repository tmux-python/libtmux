"""Constant variables for libtmux."""

import enum
import typing as t


class ResizeAdjustmentDirection(enum.Enum):
    """Used for *adjustment* in ``resize_window``, ``resize_pane``."""

    Up = "UP"
    Down = "DOWN"
    Left = "LEFT"
    Right = "RIGHT"


RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP: t.Dict[ResizeAdjustmentDirection, str] = {
    ResizeAdjustmentDirection.Up: "-U",
    ResizeAdjustmentDirection.Down: "-D",
    ResizeAdjustmentDirection.Left: "-L",
    ResizeAdjustmentDirection.Right: "-R",
}


class WindowDirection(enum.Enum):
    """Used for *adjustment* in :meth:`Session.new_window()`."""

    Before = "BEFORE"
    After = "AFTER"


WINDOW_DIRECTION_FLAG_MAP: t.Dict[WindowDirection, str] = {
    WindowDirection.Before: "-b",
    WindowDirection.After: "-a",
}


class PaneDirection(enum.Enum):
    """Used for *adjustment* in :meth:`Pane.split()`."""

    Above = "ABOVE"
    Below = "BELOW"  # default with no args
    Right = "RIGHT"
    Left = "LEFT"


PANE_DIRECTION_FLAG_MAP: t.Dict[PaneDirection, t.List[str]] = {
    # -v is assumed, but for explicitness it is passed
    PaneDirection.Above: ["-v", "-b"],
    PaneDirection.Below: ["-v"],
    PaneDirection.Right: ["-h"],
    PaneDirection.Left: ["-h", "-b"],
}


class _DefaultOptionScope:
    # Sentinel value for default scope
    ...


DEFAULT_OPTION_SCOPE: _DefaultOptionScope = _DefaultOptionScope()


class OptionScope(enum.Enum):
    """Scope used with ``set-option`` and ``show-option(s)`` commands."""

    Server = "SERVER"
    Session = "SESSION"
    Window = "WINDOW"
    Pane = "PANE"


OPTION_SCOPE_FLAG_MAP: t.Dict[OptionScope, str] = {
    OptionScope.Server: "-s",
    OptionScope.Session: "",
    OptionScope.Window: "-w",
    OptionScope.Pane: "-p",
}

HOOK_SCOPE_FLAG_MAP: t.Dict[OptionScope, str] = {
    OptionScope.Server: "",
    OptionScope.Session: "",
    OptionScope.Window: "-w",
    OptionScope.Pane: "-p",
}
