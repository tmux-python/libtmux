"""Tools for hydrating tmux data into python dataclass objects."""

from __future__ import annotations

import dataclasses
import functools
import logging
import shlex
import typing as t
from collections.abc import Iterable

from libtmux import exc
from libtmux._compat import LooseVersion
from libtmux.common import get_version, raise_if_stderr, tmux_cmd
from libtmux.formats import FORMAT_SEPARATOR

if t.TYPE_CHECKING:
    ListCmd = t.Literal["list-sessions", "list-windows", "list-panes", "list-clients"]
    ListExtraArgs = Iterable[str] | None

    from libtmux.server import Server

logger = logging.getLogger(__name__)


OutputRaw = dict[str, t.Any]
OutputsRaw = list[OutputRaw]


SCOPES_BY_LIST_CMD: dict[str, frozenset[str]] = {
    "list-sessions": frozenset({"universal", "session"}),
    "list-windows": frozenset({"universal", "session", "window"}),
    "list-panes": frozenset({"universal", "session", "window", "pane"}),
    "list-clients": frozenset({"universal", "session", "client"}),
}
"""Format-token scopes a given tmux ``list-*`` subcommand can resolve.

A token whose scope is in the set is safe to include in that subcommand's
``-F`` template. A token whose scope is *outside* the set may be unknown to
the format engine in that context, or in older tmux releases trigger a
server-side fault — exclude it from the format string.
"""


FIELD_VERSION: dict[str, str] = {}
"""Minimum tmux version that registers each format token.

Field names absent from this dict default to ``"3.2a"`` (always-safe within
the supported tmux range). Entries here represent tokens added after 3.2a
that need explicit gating to keep the ``-F`` template compatible with older
tmux versions.
"""


# Field-name prefixes that map to a single format-token scope. Resolved by
# :func:`_token_scope`. Order matters: longer prefixes win (e.g.
# ``copy_cursor_`` is a runtime token, not a generic ``copy_`` one).
_SCOPE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("copy_cursor_", "event"),
    ("pane_", "pane"),
    ("window_", "window"),
    ("session_", "session"),
    ("client_", "client"),
    ("buffer_", "buffer"),
    ("mouse_", "event"),
    ("cursor_", "event"),
    ("selection_", "event"),
    ("scroll_", "event"),
    ("popup_", "event"),
)

# Per-token scope overrides for fields whose name doesn't follow the prefix
# convention. Verified against the corresponding ``format_cb_*`` in tmux's
# ``format.c`` (which context the callback dereferences — wp, wl, s, or c).
# Entries are added by the scope-gate fix commits as misclassifications are
# discovered.
_SCOPE_OVERRIDES: dict[str, str] = {}


# Standalone tokens not captured by the prefix table.
_UNIVERSAL_TOKENS: frozenset[str] = frozenset(
    {
        "active_window_index",
        "alternate_on",
        "alternate_saved_x",
        "alternate_saved_y",
        "command_list_alias",
        "command_list_name",
        "command_list_usage",
        "config_files",
        "current_file",
        "history_bytes",
        "history_limit",
        "history_size",
        "host",
        "host_short",
        "insert_flag",
        "keypad_cursor_flag",
        "keypad_flag",
        "last_window_index",
        "line",
        "next_session_id",
        "origin_flag",
        "pid",
        "search_match",
        "socket_path",
        "start_time",
        "uid",
        "user",
        "version",
        "wrap_flag",
    }
)


def _token_scope(field_name: str) -> str:
    """Resolve a format token's scope from its name.

    Returns ``"universal"`` for cross-scope tokens (e.g. ``version``,
    ``socket_path``, ``host``). Returns ``"event"`` for runtime-only tokens
    that never appear in a ``list-*`` output (mouse, cursor, selection,
    popup). Returns ``"pane"`` / ``"window"`` / ``"session"`` / ``"client"``
    / ``"buffer"`` for scope-prefixed tokens.

    Examples
    --------
    >>> from libtmux.neo import _token_scope
    >>> _token_scope("pane_id")
    'pane'
    >>> _token_scope("window_zoomed_flag")
    'window'
    >>> _token_scope("client_name")
    'client'
    >>> _token_scope("version")
    'universal'
    >>> _token_scope("mouse_x")
    'event'

    Tokens whose name doesn't carry a scope prefix can still be scope-gated
    via :data:`_SCOPE_OVERRIDES` (verified against tmux's ``format_cb_*``).
    """
    override = _SCOPE_OVERRIDES.get(field_name)
    if override is not None:
        return override
    for prefix, scope in _SCOPE_PREFIXES:
        if field_name.startswith(prefix):
            return scope
    if field_name in _UNIVERSAL_TOKENS:
        return "universal"
    return "universal"


def _normalize_tmux_version(version: str) -> LooseVersion:
    """Convert a tmux version string into a comparable :class:`LooseVersion`.

    tmux master is reported as ``"master"`` (or e.g. ``"3.6a-master"``);
    treat it as larger than any tagged release.

    Examples
    --------
    >>> from libtmux.neo import _normalize_tmux_version
    >>> _normalize_tmux_version("3.6a") < _normalize_tmux_version("master")
    True
    >>> _normalize_tmux_version("3.2a") < _normalize_tmux_version("3.6a")
    True
    """
    if "master" in version.lower():
        return LooseVersion("99.0")
    return LooseVersion(version)


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
    client_activity: str | None = None
    client_cell_height: str | None = None
    client_cell_width: str | None = None
    client_control_mode: str | None = None
    client_created: str | None = None
    client_discarded: str | None = None
    client_flags: str | None = None
    client_height: str | None = None
    client_key_table: str | None = None
    client_last_session: str | None = None
    client_mode_format: str | None = None
    client_name: str | None = None
    client_pid: str | None = None
    client_prefix: str | None = None
    client_readonly: str | None = None
    client_session: str | None = None
    client_termfeatures: str | None = None
    client_termname: str | None = None
    client_termtype: str | None = None
    client_tty: str | None = None
    client_uid: str | None = None
    client_user: str | None = None
    client_utf8: str | None = None
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
    pane_dead: str | None = None
    pane_dead_signal: str | None = None
    pane_dead_status: str | None = None
    pane_dead_time: str | None = None
    pane_fg: str | None = None
    pane_format: str | None = None
    pane_height: str | None = None
    pane_id: str | None = None
    pane_in_mode: str | None = None
    pane_index: str | None = None
    pane_input_off: str | None = None
    pane_last: str | None = None
    pane_left: str | None = None
    pane_marked: str | None = None
    pane_marked_set: str | None = None
    pane_mode: str | None = None
    pane_path: str | None = None
    pane_pid: str | None = None
    pane_pipe: str | None = None
    pane_right: str | None = None
    pane_search_string: str | None = None
    pane_start_command: str | None = None
    pane_start_path: str | None = None
    pane_synchronized: str | None = None
    pane_tabs: str | None = None
    pane_title: str | None = None
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
    session_format: str | None = None
    session_group: str | None = None
    session_group_attached: str | None = None
    session_group_attached_list: str | None = None
    session_group_list: str | None = None
    session_group_many_attached: str | None = None
    session_group_size: str | None = None
    session_grouped: str | None = None
    session_id: str | None = None
    session_last_attached: str | None = None
    session_many_attached: str | None = None
    session_marked: str | None = None
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
    window_active_clients_list: str | None = None
    window_active_sessions: str | None = None
    window_active_sessions_list: str | None = None
    window_activity: str | None = None
    window_activity_flag: str | None = None
    window_bell_flag: str | None = None
    window_bigger: str | None = None
    window_cell_height: str | None = None
    window_cell_width: str | None = None
    window_end_flag: str | None = None
    window_flags: str | None = None
    window_format: str | None = None
    window_height: str | None = None
    window_id: str | None = None
    window_index: str | None = None
    window_last_flag: str | None = None
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
    window_silence_flag: str | None = None
    window_stack_index: str | None = None
    window_start_flag: str | None = None
    window_visible_layout: str | None = None
    window_width: str | None = None
    window_zoomed_flag: str | None = None
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


@functools.cache
def get_output_format(
    list_cmd: str = "list-panes",
    tmux_version: str = "3.2a",
) -> tuple[tuple[str, ...], str]:
    """Return field names and tmux format string filtered by scope and version.

    Only emits tokens whose scope is reachable from *list_cmd* (per
    :data:`SCOPES_BY_LIST_CMD`) and whose minimum tmux version (per
    :data:`FIELD_VERSION`) is at or below *tmux_version*. Runtime-only
    tokens (``mouse_*``, ``cursor_*``, popups) are excluded from every
    ``list-*`` template — they only resolve in event-time format contexts.

    Parameters
    ----------
    list_cmd : str
        The tmux list subcommand the format string is being built for.
        Determines which token scopes are reachable.
    tmux_version : str
        The live tmux version. Used to gate post-3.2a tokens. Defaults to
        ``"3.2a"`` (the project's minimum) for safe fallback when the
        caller can't yet detect the version.

    Returns
    -------
    tuple[tuple[str, ...], str]
        A tuple of (field_names, tmux_format_string) restricted to tokens
        the given *list_cmd* and *tmux_version* can resolve.

    Examples
    --------
    >>> from libtmux.neo import get_output_format
    >>> fields, fmt = get_output_format("list-sessions", "3.6a")
    >>> 'session_id' in fields
    True
    >>> 'pane_id' in fields
    False
    >>> 'server' in fields
    False

    Pane scope picks up window and session tokens too:

    >>> fields, _ = get_output_format("list-panes", "3.6a")
    >>> all(t in fields for t in ('pane_id', 'window_id', 'session_id'))
    True

    Client scope is isolated from pane/window tokens:

    >>> fields, _ = get_output_format("list-clients", "3.6a")
    >>> 'pane_id' in fields
    False
    """
    allowed_scopes = SCOPES_BY_LIST_CMD.get(
        list_cmd,
        frozenset({"universal", "session", "window", "pane"}),
    )
    live_ver = _normalize_tmux_version(tmux_version)

    formats: list[str] = []
    for f in Obj.__dataclass_fields__:
        if f == "server":
            continue
        if _token_scope(f) not in allowed_scopes:
            continue
        min_v = FIELD_VERSION.get(f)
        if min_v is not None and _normalize_tmux_version(min_v) > live_ver:
            continue
        formats.append(f)

    tmux_format = "".join(f"#{{{n}}}{FORMAT_SEPARATOR}" for n in formats)
    return tuple(formats), tmux_format


def parse_output(
    output: str,
    list_cmd: str = "list-panes",
    tmux_version: str = "3.2a",
) -> OutputRaw:
    """Parse a tmux ``-F`` line into a dict keyed by Obj field name.

    The (*list_cmd*, *tmux_version*) pair must match what was passed to
    :func:`get_output_format` when the ``-F`` template was built —
    otherwise the field order won't line up with the split values.

    Parameters
    ----------
    output : str
        Raw tmux output line produced with a template from
        :func:`get_output_format`.
    list_cmd : str
        Same value passed to :func:`get_output_format`.
    tmux_version : str
        Same value passed to :func:`get_output_format`.

    Returns
    -------
    OutputRaw
        A dict mapping field names to non-empty string values.

    Examples
    --------
    >>> from libtmux.neo import get_output_format, parse_output
    >>> from libtmux.formats import FORMAT_SEPARATOR
    >>> fields, fmt = get_output_format("list-sessions", "3.6a")
    >>> values = [''] * len(fields)
    >>> values[fields.index('session_id')] = '$1'
    >>> result = parse_output(
    ...     FORMAT_SEPARATOR.join(values) + FORMAT_SEPARATOR,
    ...     list_cmd="list-sessions",
    ...     tmux_version="3.6a",
    ... )
    >>> result['session_id']
    '$1'
    >>> 'pane_id' in result
    False
    """
    formats, _ = get_output_format(list_cmd, tmux_version)
    values = output.split(FORMAT_SEPARATOR)

    # Remove the trailing empty string from the split
    if values and values[-1] == "":
        values = values[:-1]

    formatter = dict(zip(formats, values, strict=True))
    return {k: v for k, v in formatter.items() if v}


def fetch_objs(
    server: Server,
    list_cmd: ListCmd,
    list_extra_args: ListExtraArgs = None,
    filter: str | None = None,  # noqa: A002
) -> OutputsRaw:
    """Fetch a listing of raw data from a tmux command.

    Runs a tmux list command (e.g. ``list-sessions``) with the format string
    from :func:`get_output_format` and parses each line of output into a dict.

    Parameters
    ----------
    server : :class:`~libtmux.server.Server`
        The tmux server to query.
    list_cmd : ListCmd
        The tmux list command to run, e.g. ``"list-sessions"``,
        ``"list-windows"``, or ``"list-panes"``.
    list_extra_args : ListExtraArgs, optional
        Extra arguments appended to the tmux command (e.g. ``("-a",)``
        for all windows/panes, or ``["-t", session_id]`` to filter).
    filter : str, optional
        Filter expression evaluated by tmux's format engine (``-f`` flag).
        Objects for which the expanded expression is "false" (empty string,
        "0") are omitted from the result. Pushes filtering into tmux's C
        code instead of Python post-processing.

        .. versionadded:: 0.57

    Returns
    -------
    OutputsRaw
        A list of dicts, each mapping tmux format field names to their
        non-empty string values.

    Raises
    ------
    :exc:`~libtmux.exc.LibTmuxException`
        If the tmux command writes to stderr.

    Examples
    --------
    >>> from libtmux.neo import fetch_objs
    >>> objs = fetch_objs(server=server, list_cmd="list-sessions")
    >>> isinstance(objs, list)
    True
    >>> isinstance(objs[0], dict)
    True
    >>> 'session_id' in objs[0]
    True
    """
    tmux_version = str(get_version(tmux_bin=server.tmux_bin))
    _fields, format_string = get_output_format(list_cmd, tmux_version)

    cmd_args: list[str | int] = []

    if server.socket_name:
        cmd_args.insert(0, f"-L{server.socket_name}")
    if server.socket_path:
        cmd_args.insert(0, f"-S{server.socket_path}")

    tmux_cmds = [
        *cmd_args,
        list_cmd,
    ]

    if list_extra_args is not None and isinstance(list_extra_args, Iterable):
        tmux_cmds.extend(list(list_extra_args))

    if filter is not None:
        tmux_cmds.extend(["-f", filter])

    tmux_cmds.append(f"-F{format_string}")

    cmd_str: str | None = None

    if logger.isEnabledFor(logging.DEBUG):
        cmd_str = shlex.join([str(x) for x in tmux_cmds])
        logger.debug(
            "tmux list queried",
            extra={
                "tmux_subcommand": list_cmd,
                "tmux_cmd": cmd_str,
            },
        )

    proc = tmux_cmd(
        *tmux_cmds,
        tmux_bin=server.tmux_bin,
    )

    raise_if_stderr(proc, list_cmd)

    outputs = [parse_output(line, list_cmd, tmux_version) for line in proc.stdout]

    if logger.isEnabledFor(logging.DEBUG):
        if cmd_str is None:
            cmd_str = shlex.join([str(x) for x in tmux_cmds])
        logger.debug(
            "tmux list parsed",
            extra={
                "tmux_subcommand": list_cmd,
                "tmux_cmd": cmd_str,
                "tmux_stdout_len": len(proc.stdout),
            },
        )

    return outputs


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
