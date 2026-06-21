"""Concrete seed operations.

Importing this package registers each operation in the default registry
(:data:`libtmux.experimental.ops.registry.registry`) as a side effect of the
``@register`` decorator on each class.
"""

from __future__ import annotations

from libtmux.experimental.ops._ops.break_pane import BreakPane
from libtmux.experimental.ops._ops.capture_pane import CapturePane
from libtmux.experimental.ops._ops.clear_history import ClearHistory
from libtmux.experimental.ops._ops.detach_client import DetachClient
from libtmux.experimental.ops._ops.display_message import DisplayMessage
from libtmux.experimental.ops._ops.has_session import HasSession
from libtmux.experimental.ops._ops.join_pane import JoinPane
from libtmux.experimental.ops._ops.kill_pane import KillPane
from libtmux.experimental.ops._ops.kill_session import KillSession
from libtmux.experimental.ops._ops.kill_window import KillWindow
from libtmux.experimental.ops._ops.last_pane import LastPane
from libtmux.experimental.ops._ops.list_clients import ListClients
from libtmux.experimental.ops._ops.list_panes import ListPanes
from libtmux.experimental.ops._ops.list_sessions import ListSessions
from libtmux.experimental.ops._ops.list_windows import ListWindows
from libtmux.experimental.ops._ops.move_pane import MovePane
from libtmux.experimental.ops._ops.new_session import NewSession
from libtmux.experimental.ops._ops.new_window import NewWindow
from libtmux.experimental.ops._ops.pipe_pane import PipePane
from libtmux.experimental.ops._ops.refresh_client import RefreshClient
from libtmux.experimental.ops._ops.rename_session import RenameSession
from libtmux.experimental.ops._ops.rename_window import RenameWindow
from libtmux.experimental.ops._ops.resize_pane import ResizePane
from libtmux.experimental.ops._ops.respawn_pane import RespawnPane
from libtmux.experimental.ops._ops.select_layout import SelectLayout
from libtmux.experimental.ops._ops.select_pane import SelectPane
from libtmux.experimental.ops._ops.send_keys import SendKeys
from libtmux.experimental.ops._ops.show_options import ShowOptions
from libtmux.experimental.ops._ops.split_window import SplitWindow
from libtmux.experimental.ops._ops.swap_pane import SwapPane
from libtmux.experimental.ops._ops.switch_client import SwitchClient

__all__ = (
    "BreakPane",
    "CapturePane",
    "ClearHistory",
    "DetachClient",
    "DisplayMessage",
    "HasSession",
    "JoinPane",
    "KillPane",
    "KillSession",
    "KillWindow",
    "LastPane",
    "ListClients",
    "ListPanes",
    "ListSessions",
    "ListWindows",
    "MovePane",
    "NewSession",
    "NewWindow",
    "PipePane",
    "RefreshClient",
    "RenameSession",
    "RenameWindow",
    "ResizePane",
    "RespawnPane",
    "SelectLayout",
    "SelectPane",
    "SendKeys",
    "ShowOptions",
    "SplitWindow",
    "SwapPane",
    "SwitchClient",
)
