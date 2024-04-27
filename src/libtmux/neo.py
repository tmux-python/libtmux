"""Tools for hydrating tmux data into python dataclass objects."""

import dataclasses
import logging
import typing as t

from libtmux import exc
from libtmux.common import tmux_cmd
from libtmux.formats import FORMAT_SEPARATOR

if t.TYPE_CHECKING:
    ListCmd = t.Literal["list-sessions", "list-windows", "list-panes"]
    ListExtraArgs = t.Optional[t.Iterable[str]]

    from libtmux.server import Server

logger = logging.getLogger(__name__)


OutputRaw = t.Dict[str, t.Any]
OutputsRaw = t.List[OutputRaw]


"""
Quirks:

QUIRK_TMUX_3_1_X_0001:

- tmux 3.1 and 3.1a:
- server crash with list-panes w/ buffer_created, client_activity, client_created
"""


@dataclasses.dataclass()
class Obj:
    """Dataclass of generic tmux object."""

    server: "Server"

    active_window_index: t.Union[str, None] = None
    alternate_saved_x: t.Union[str, None] = None
    alternate_saved_y: t.Union[str, None] = None
    # See QUIRK_TMUX_3_1_X_0001
    buffer_name: t.Union[str, None] = None
    buffer_sample: t.Union[str, None] = None
    buffer_size: t.Union[str, None] = None
    # See QUIRK_TMUX_3_1_X_0001
    client_cell_height: t.Union[str, None] = None
    client_cell_width: t.Union[str, None] = None
    # See QUIRK_TMUX_3_1_X_0001
    client_discarded: t.Union[str, None] = None
    client_flags: t.Union[str, None] = None
    client_height: t.Union[str, None] = None
    client_key_table: t.Union[str, None] = None
    client_name: t.Union[str, None] = None
    client_pid: t.Union[str, None] = None
    client_termname: t.Union[str, None] = None
    client_tty: t.Union[str, None] = None
    client_uid: t.Union[str, None] = None
    client_user: t.Union[str, None] = None
    client_width: t.Union[str, None] = None
    client_written: t.Union[str, None] = None
    command_list_alias: t.Union[str, None] = None
    command_list_name: t.Union[str, None] = None
    command_list_usage: t.Union[str, None] = None
    config_files: t.Union[str, None] = None
    copy_cursor_line: t.Union[str, None] = None
    copy_cursor_word: t.Union[str, None] = None
    copy_cursor_x: t.Union[str, None] = None
    copy_cursor_y: t.Union[str, None] = None
    current_file: t.Union[str, None] = None
    cursor_character: t.Union[str, None] = None
    cursor_flag: t.Union[str, None] = None
    cursor_x: t.Union[str, None] = None
    cursor_y: t.Union[str, None] = None
    history_bytes: t.Union[str, None] = None
    history_limit: t.Union[str, None] = None
    history_size: t.Union[str, None] = None
    insert_flag: t.Union[str, None] = None
    keypad_cursor_flag: t.Union[str, None] = None
    keypad_flag: t.Union[str, None] = None
    last_window_index: t.Union[str, None] = None
    line: t.Union[str, None] = None
    mouse_all_flag: t.Union[str, None] = None
    mouse_any_flag: t.Union[str, None] = None
    mouse_button_flag: t.Union[str, None] = None
    mouse_sgr_flag: t.Union[str, None] = None
    mouse_standard_flag: t.Union[str, None] = None
    next_session_id: t.Union[str, None] = None
    origin_flag: t.Union[str, None] = None
    pane_active: t.Union[str, None] = None  # Not detected by script
    pane_at_bottom: t.Union[str, None] = None
    pane_at_left: t.Union[str, None] = None
    pane_at_right: t.Union[str, None] = None
    pane_at_top: t.Union[str, None] = None
    pane_bg: t.Union[str, None] = None
    pane_bottom: t.Union[str, None] = None
    pane_current_command: t.Union[str, None] = None
    pane_current_path: t.Union[str, None] = None
    pane_dead_signal: t.Union[str, None] = None
    pane_dead_status: t.Union[str, None] = None
    pane_dead_time: t.Union[str, None] = None
    pane_fg: t.Union[str, None] = None
    pane_height: t.Union[str, None] = None
    pane_id: t.Union[str, None] = None
    pane_index: t.Union[str, None] = None
    pane_left: t.Union[str, None] = None
    pane_pid: t.Union[str, None] = None
    pane_right: t.Union[str, None] = None
    pane_search_string: t.Union[str, None] = None
    pane_start_command: t.Union[str, None] = None
    pane_start_path: t.Union[str, None] = None
    pane_tabs: t.Union[str, None] = None
    pane_top: t.Union[str, None] = None
    pane_tty: t.Union[str, None] = None
    pane_width: t.Union[str, None] = None
    pid: t.Union[str, None] = None
    scroll_position: t.Union[str, None] = None
    scroll_region_lower: t.Union[str, None] = None
    scroll_region_upper: t.Union[str, None] = None
    search_match: t.Union[str, None] = None
    selection_end_x: t.Union[str, None] = None
    selection_end_y: t.Union[str, None] = None
    selection_start_x: t.Union[str, None] = None
    selection_start_y: t.Union[str, None] = None
    session_activity: t.Union[str, None] = None
    session_alerts: t.Union[str, None] = None
    session_attached: t.Union[str, None] = None
    session_attached_list: t.Union[str, None] = None
    session_created: t.Union[str, None] = None
    session_group: t.Union[str, None] = None
    session_group_attached: t.Union[str, None] = None
    session_group_list: t.Union[str, None] = None
    session_group_size: t.Union[str, None] = None
    session_id: t.Union[str, None] = None
    session_last_attached: t.Union[str, None] = None
    session_name: t.Union[str, None] = None
    session_path: t.Union[str, None] = None
    session_stack: t.Union[str, None] = None
    session_windows: t.Union[str, None] = None
    socket_path: t.Union[str, None] = None
    start_time: t.Union[str, None] = None
    uid: t.Union[str, None] = None
    user: t.Union[str, None] = None
    version: t.Union[str, None] = None
    window_active: t.Union[str, None] = None  # Not detected by script
    window_active_clients: t.Union[str, None] = None
    window_active_sessions: t.Union[str, None] = None
    window_activity: t.Union[str, None] = None
    window_cell_height: t.Union[str, None] = None
    window_cell_width: t.Union[str, None] = None
    window_height: t.Union[str, None] = None
    window_id: t.Union[str, None] = None
    window_index: t.Union[str, None] = None
    window_layout: t.Union[str, None] = None
    window_linked: t.Union[str, None] = None
    window_linked_sessions: t.Union[str, None] = None
    window_linked_sessions_list: t.Union[str, None] = None
    window_marked_flag: t.Union[str, None] = None
    window_name: t.Union[str, None] = None
    window_offset_x: t.Union[str, None] = None
    window_offset_y: t.Union[str, None] = None
    window_panes: t.Union[str, None] = None
    window_raw_flags: t.Union[str, None] = None
    window_stack_index: t.Union[str, None] = None
    window_width: t.Union[str, None] = None
    wrap_flag: t.Union[str, None] = None

    def _refresh(
        self,
        obj_key: str,
        obj_id: str,
        list_cmd: "ListCmd" = "list-panes",
        list_extra_args: "t.Optional[ListExtraArgs]" = None,
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
    server: "Server",
    list_cmd: "ListCmd",
    list_extra_args: "t.Optional[ListExtraArgs]" = None,
) -> OutputsRaw:
    """Fetch a listing of raw data from a tmux command."""
    formats = list(Obj.__dataclass_fields__.keys())

    cmd_args: t.List[t.Union[str, int]] = []

    if server.socket_name:
        cmd_args.insert(0, f"-L{server.socket_name}")
    if server.socket_path:
        cmd_args.insert(0, f"-S{server.socket_path}")
    tmux_formats = [f"#{{{f}}}{FORMAT_SEPARATOR}" for f in formats]

    tmux_cmds = [
        *cmd_args,
        list_cmd,
    ]

    if list_extra_args is not None and isinstance(list_extra_args, t.Iterable):
        tmux_cmds.extend(list(list_extra_args))

    tmux_cmds.append("-F{}".format("".join(tmux_formats)))

    proc = tmux_cmd(*tmux_cmds)  # output

    if proc.stderr:
        raise exc.LibTmuxException(proc.stderr)

    obj_output = proc.stdout

    obj_formatters = [
        dict(zip(formats, formatter.split(FORMAT_SEPARATOR)))
        for formatter in obj_output
    ]

    # Filter empty values
    return [{k: v for k, v in formatter.items() if v} for formatter in obj_formatters]


def fetch_obj(
    server: "Server",
    obj_key: str,
    obj_id: str,
    list_cmd: "ListCmd" = "list-panes",
    list_extra_args: "t.Optional[ListExtraArgs]" = None,
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
