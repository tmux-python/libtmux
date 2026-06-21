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
from libtmux.experimental.ops._ops.kill_server import KillServer
from libtmux.experimental.ops._ops.kill_session import KillSession
from libtmux.experimental.ops._ops.kill_window import KillWindow
from libtmux.experimental.ops._ops.last_pane import LastPane
from libtmux.experimental.ops._ops.last_window import LastWindow
from libtmux.experimental.ops._ops.link_window import LinkWindow
from libtmux.experimental.ops._ops.list_clients import ListClients
from libtmux.experimental.ops._ops.list_panes import ListPanes
from libtmux.experimental.ops._ops.list_sessions import ListSessions
from libtmux.experimental.ops._ops.list_windows import ListWindows
from libtmux.experimental.ops._ops.move_pane import MovePane
from libtmux.experimental.ops._ops.move_window import MoveWindow
from libtmux.experimental.ops._ops.new_session import NewSession
from libtmux.experimental.ops._ops.new_window import NewWindow
from libtmux.experimental.ops._ops.next_window import NextWindow
from libtmux.experimental.ops._ops.pipe_pane import PipePane
from libtmux.experimental.ops._ops.previous_window import PreviousWindow
from libtmux.experimental.ops._ops.refresh_client import RefreshClient
from libtmux.experimental.ops._ops.rename_session import RenameSession
from libtmux.experimental.ops._ops.rename_window import RenameWindow
from libtmux.experimental.ops._ops.resize_pane import ResizePane
from libtmux.experimental.ops._ops.resize_window import ResizeWindow
from libtmux.experimental.ops._ops.respawn_pane import RespawnPane
from libtmux.experimental.ops._ops.respawn_window import RespawnWindow
from libtmux.experimental.ops._ops.rotate_window import RotateWindow
from libtmux.experimental.ops._ops.run_shell import RunShell
from libtmux.experimental.ops._ops.select_layout import SelectLayout
from libtmux.experimental.ops._ops.select_pane import SelectPane
from libtmux.experimental.ops._ops.select_window import SelectWindow
from libtmux.experimental.ops._ops.send_keys import SendKeys
from libtmux.experimental.ops._ops.set_environment import SetEnvironment
from libtmux.experimental.ops._ops.set_hook import SetHook
from libtmux.experimental.ops._ops.set_option import SetOption
from libtmux.experimental.ops._ops.set_window_option import SetWindowOption
from libtmux.experimental.ops._ops.show_options import ShowOptions
from libtmux.experimental.ops._ops.source_file import SourceFile
from libtmux.experimental.ops._ops.split_window import SplitWindow
from libtmux.experimental.ops._ops.start_server import StartServer
from libtmux.experimental.ops._ops.suspend_client import SuspendClient
from libtmux.experimental.ops._ops.swap_pane import SwapPane
from libtmux.experimental.ops._ops.swap_window import SwapWindow
from libtmux.experimental.ops._ops.switch_client import SwitchClient
from libtmux.experimental.ops._ops.unlink_window import UnlinkWindow

__all__ = (
    "BreakPane",
    "CapturePane",
    "ClearHistory",
    "DetachClient",
    "DisplayMessage",
    "HasSession",
    "JoinPane",
    "KillPane",
    "KillServer",
    "KillSession",
    "KillWindow",
    "LastPane",
    "LastWindow",
    "LinkWindow",
    "ListClients",
    "ListPanes",
    "ListSessions",
    "ListWindows",
    "MovePane",
    "MoveWindow",
    "NewSession",
    "NewWindow",
    "NextWindow",
    "PipePane",
    "PreviousWindow",
    "RefreshClient",
    "RenameSession",
    "RenameWindow",
    "ResizePane",
    "ResizeWindow",
    "RespawnPane",
    "RespawnWindow",
    "RotateWindow",
    "RunShell",
    "SelectLayout",
    "SelectPane",
    "SelectWindow",
    "SendKeys",
    "SetEnvironment",
    "SetHook",
    "SetOption",
    "SetWindowOption",
    "ShowOptions",
    "SourceFile",
    "SplitWindow",
    "StartServer",
    "SuspendClient",
    "SwapPane",
    "SwapWindow",
    "SwitchClient",
    "UnlinkWindow",
)
