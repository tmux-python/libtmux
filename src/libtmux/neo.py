"""Tools for hydrating tmux data into python dataclass objects."""

from __future__ import annotations

import dataclasses
import logging
import typing as t
from collections.abc import Iterable

from libtmux import exc
from libtmux.common import tmux_cmd
from libtmux.formats import FORMAT_SEPARATOR

if t.TYPE_CHECKING:
    ListCmd = t.Literal["list-sessions", "list-windows", "list-panes"]
    ListExtraArgs = Iterable[str] | None

    from libtmux.server import Server

logger = logging.getLogger(__name__)


OutputRaw = dict[str, t.Any]
OutputsRaw = list[OutputRaw]


@dataclasses.dataclass()
class Obj:
    """Dataclass of generic tmux object."""

    server: Server

    active_window_index: str | None = None
    alternate_saved_x: str | None = None
    alternate_saved_y: str | None = None
    buffer_name: str | None = None
    buffer_sample: str | None = None
    buffer_size: str | None = None
    client_cell_height: str | None = None
    client_cell_width: str | None = None
    client_discarded: str | None = None
    client_flags: str | None = None
    client_height: str | None = None
    client_key_table: str | None = None
    client_name: str | None = None
    client_pid: str | None = None
    client_termname: str | None = None
    client_tty: str | None = None
    client_uid: str | None = None
    client_user: str | None = None
    client_width: str | None = None
    client_written: str | None = None
    command_list_alias: str | None = None
    command_list_name: str | None = None
    command_list_usage: str | None = None
    config_files: str | None = None
    copy_cursor_line: str | None = None
    copy_cursor_word: str | None = None
    copy_cursor_x: str | None = None
    copy_cursor_y: str | None = None
    current_file: str | None = None
    cursor_character: str | None = None
    cursor_flag: str | None = None
    cursor_x: str | None = None
    cursor_y: str | None = None
    history_bytes: str | None = None
    history_limit: str | None = None
    history_size: str | None = None
    insert_flag: str | None = None
    keypad_cursor_flag: str | None = None
    keypad_flag: str | None = None
    last_window_index: str | None = None
    line: str | None = None
    mouse_all_flag: str | None = None
    mouse_any_flag: str | None = None
    mouse_button_flag: str | None = None
    mouse_sgr_flag: str | None = None
    mouse_standard_flag: str | None = None
    next_session_id: str | None = None
    origin_flag: str | None = None
    pane_active: str | None = None  # Not detected by script
    pane_at_bottom: str | None = None
    pane_at_left: str | None = None
    pane_at_right: str | None = None
    pane_at_top: str | None = None
    pane_bg: str | None = None
    pane_bottom: str | None = None
    pane_current_command: str | None = None
    pane_current_path: str | None = None
    pane_dead_signal: str | None = None
    pane_dead_status: str | None = None
    pane_dead_time: str | None = None
    pane_fg: str | None = None
    pane_height: str | None = None
    pane_id: str | None = None
    pane_index: str | None = None
    pane_left: str | None = None
    pane_pid: str | None = None
    pane_right: str | None = None
    pane_search_string: str | None = None
    pane_start_command: str | None = None
    pane_start_path: str | None = None
    pane_tabs: str | None = None
    pane_top: str | None = None
    pane_tty: str | None = None
    pane_width: str | None = None
    pid: str | None = None
    scroll_position: str | None = None
    scroll_region_lower: str | None = None
    scroll_region_upper: str | None = None
    search_match: str | None = None
    selection_end_x: str | None = None
    selection_end_y: str | None = None
    selection_start_x: str | None = None
    selection_start_y: str | None = None
    session_activity: str | None = None
    session_alerts: str | None = None
    session_attached: str | None = None
    session_attached_list: str | None = None
    session_created: str | None = None
    session_group: str | None = None
    session_group_attached: str | None = None
    session_group_list: str | None = None
    session_group_size: str | None = None
    session_id: str | None = None
    session_last_attached: str | None = None
    session_name: str | None = None
    session_path: str | None = None
    session_stack: str | None = None
    session_windows: str | None = None
    socket_path: str | None = None
    start_time: str | None = None
    uid: str | None = None
    user: str | None = None
    version: str | None = None
    window_active: str | None = None  # Not detected by script
    window_active_clients: str | None = None
    window_active_sessions: str | None = None
    window_activity: str | None = None
    window_cell_height: str | None = None
    window_cell_width: str | None = None
    window_height: str | None = None
    window_id: str | None = None
    window_index: str | None = None
    window_layout: str | None = None
    window_linked: str | None = None
    window_linked_sessions: str | None = None
    window_linked_sessions_list: str | None = None
    window_marked_flag: str | None = None
    window_name: str | None = None
    window_offset_x: str | None = None
    window_offset_y: str | None = None
    window_panes: str | None = None
    window_raw_flags: str | None = None
    window_stack_index: str | None = None
    window_width: str | None = None
    wrap_flag: str | None = None

    def _refresh(
        self,
        obj_key: str,
        obj_id: str,
        list_cmd: ListCmd = "list-panes",
        list_extra_args: ListExtraArgs = None,
    ) -> None:
        assert isinstance(obj_id, str)
        obj = fetch_obj(
            obj_key=obj_key,
            obj_id=obj_id,
            list_cmd=list_cmd,
            list_extra_args=list_extra_args,
            server=self.server,
        )
        assert obj is not None
        if obj is not None:
            for k, v in obj.items():
                setattr(self, k, v)


def fetch_objs(
    server: Server,
    list_cmd: ListCmd,
    list_extra_args: ListExtraArgs = None,
) -> OutputsRaw:
    """Fetch a listing of raw data from a tmux command."""
    formats = list(Obj.__dataclass_fields__.keys())

    cmd_args: list[str | int] = []

    if server.socket_name:
        cmd_args.insert(0, f"-L{server.socket_name}")
    if server.socket_path:
        cmd_args.insert(0, f"-S{server.socket_path}")
    tmux_formats = [f"#{{{f}}}{FORMAT_SEPARATOR}" for f in formats]

    tmux_cmds = [
        *cmd_args,
        list_cmd,
    ]

    if list_extra_args is not None and isinstance(list_extra_args, Iterable):
        tmux_cmds.extend(list(list_extra_args))

    tmux_cmds.append("-F{}".format("".join(tmux_formats)))

    proc = tmux_cmd(*tmux_cmds)  # output

    if proc.stderr:
        raise exc.LibTmuxException(proc.stderr)

    obj_output = proc.stdout

    obj_formatters = [
        dict(zip(formats, formatter.split(FORMAT_SEPARATOR), strict=False))
        for formatter in obj_output
    ]

    # Filter empty values
    return [{k: v for k, v in formatter.items() if v} for formatter in obj_formatters]


def fetch_obj(
    server: Server,
    obj_key: str,
    obj_id: str,
    list_cmd: ListCmd = "list-panes",
    list_extra_args: ListExtraArgs = None,
) -> OutputRaw:
    """Fetch raw data from tmux command."""
    obj_formatters_filtered = fetch_objs(
        server=server,
        list_cmd=list_cmd,
        list_extra_args=list_extra_args,
    )

    obj = None
    for _obj in obj_formatters_filtered:
        if _obj.get(obj_key) == obj_id:
            obj = _obj

    if obj is None:
        raise exc.TmuxObjectDoesNotExist(
            obj_key=obj_key,
            obj_id=obj_id,
            list_cmd=list_cmd,
            list_extra_args=list_extra_args,
        )

    assert obj is not None

    return obj
