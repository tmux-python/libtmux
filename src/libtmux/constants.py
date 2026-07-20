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


class _DefaultOptionScope:
    """Sentinel type for the ``scope=`` parameter's default value.

    The lone instance :data:`DEFAULT_OPTION_SCOPE` is used as the
    default for option-related helpers; receiving methods use ``is``
    comparison against the sentinel to detect "no explicit scope was
    passed" and infer the right scope from the bound object type.
    """


DEFAULT_OPTION_SCOPE: _DefaultOptionScope = _DefaultOptionScope()
"""Sentinel default for ``scope=`` parameters on option / hook helpers.

When ``scope is DEFAULT_OPTION_SCOPE`` the caller hasn't selected an
explicit :class:`OptionScope`; the receiving method
(:meth:`Pane._show_option`, :meth:`Server.show_options`, etc.)
infers the appropriate scope from the bound object type
(``Pane`` → ``OptionScope.Pane``, ``Server`` → ``OptionScope.Server``,
…).
"""


class OptionScope(enum.Enum):
    """Scope used with ``set-option`` and ``show-option(s)`` commands."""

    Server = "SERVER"
    Session = "SESSION"
    Window = "WINDOW"
    Pane = "PANE"


OPTION_SCOPE_FLAG_MAP: dict[OptionScope, str] = {
    OptionScope.Server: "-s",
    OptionScope.Session: "",
    OptionScope.Window: "-w",
    OptionScope.Pane: "-p",
}

HOOK_SCOPE_FLAG_MAP: dict[OptionScope, str] = {
    OptionScope.Server: "-g",
    OptionScope.Session: "",
    OptionScope.Window: "-w",
    OptionScope.Pane: "-p",
}
