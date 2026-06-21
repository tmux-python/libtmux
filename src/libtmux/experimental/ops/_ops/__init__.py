"""Concrete seed operations.

Importing this package registers each operation in the default registry
(:data:`libtmux.experimental.ops.registry.registry`) as a side effect of the
``@register`` decorator on each class.
"""

from __future__ import annotations

from libtmux.experimental.ops._ops.capture_pane import CapturePane
from libtmux.experimental.ops._ops.kill_pane import KillPane
from libtmux.experimental.ops._ops.kill_window import KillWindow
from libtmux.experimental.ops._ops.list_panes import ListPanes
from libtmux.experimental.ops._ops.list_sessions import ListSessions
from libtmux.experimental.ops._ops.list_windows import ListWindows
from libtmux.experimental.ops._ops.rename_window import RenameWindow
from libtmux.experimental.ops._ops.select_layout import SelectLayout
from libtmux.experimental.ops._ops.send_keys import SendKeys
from libtmux.experimental.ops._ops.split_window import SplitWindow

__all__ = (
    "CapturePane",
    "KillPane",
    "KillWindow",
    "ListPanes",
    "ListSessions",
    "ListWindows",
    "RenameWindow",
    "SelectLayout",
    "SendKeys",
    "SplitWindow",
)
