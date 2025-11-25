"""Tools for reading tmux data into Python objects."""

from __future__ import annotations

import dataclasses
import functools
import logging
import shlex
import typing as t
from collections.abc import Iterable

from libtmux import exc
from libtmux._compat import LooseVersion
from libtmux.common import get_version, raise_if_stderr
from libtmux.formats import FORMAT_SEPARATOR

if t.TYPE_CHECKING:
    ListCmd = t.Literal["list-sessions", "list-windows", "list-panes", "list-clients"]
    ListExtraArgs = Iterable[str] | None

    from libtmux.server import Server

logger = logging.getLogger(__name__)


OutputRaw = dict[str, t.Any]
OutputsRaw = list[OutputRaw]


SCOPES_BY_LIST_CMD: dict[str, frozenset[str]] = {
    "list-sessions": frozenset({"universal", "session", "window", "pane"}),
    "list-windows": frozenset({"universal", "session", "window", "pane"}),
    "list-panes": frozenset({"universal", "session", "window", "pane"}),
    "list-clients": frozenset({"universal", "session", "window", "pane", "client"}),
}
"""Format-token scopes a given tmux ``list-*`` subcommand can resolve.

A token whose scope is in the set is safe to include in that subcommand's
``-F`` template. A token whose scope is *outside* the set may be unavailable
for that command, so libtmux leaves it out.

The relationship is asymmetric: when tmux lists a parent object, it can also
report fields for that parent's active child. A session row can include its
current window and active pane fields, and a client row can include the
attached session, current window, and active pane. ``client`` scope is the
exception in the other direction: it appears only in ``list-clients`` because
session/window/pane listings do not have a client attachment to report.
"""


FIELD_VERSION: dict[str, str] = {
    # Post-3.2a additions (verified against tmux's format.c at each gated
    # release tag, e.g. https://github.com/tmux/tmux/blob/3.6a/format.c).
    "pane_dead_signal": "3.3",
    "pane_dead_time": "3.3",
    # tmux 3.7 additions (verified against format.c / tmux.1 at the 3.7 tag).
    "bracket_paste_flag": "3.7",
    "pane_flags": "3.7",
    "pane_floating_flag": "3.7",
    "pane_pb_progress": "3.7",
    "pane_pb_state": "3.7",
    "pane_pipe_pid": "3.7",
    "pane_x": "3.7",
    "pane_y": "3.7",
    "pane_z": "3.7",
    "pane_zoomed_flag": "3.7",
    "synchronized_output_flag": "3.7",
}
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
_SCOPE_OVERRIDES: dict[str, str] = {
    "cursor_x": "pane",  # ft->wp->base.cx
    "cursor_y": "pane",  # ft->wp->base.cy
    "cursor_flag": "pane",  # ft->wp->base.mode
    "cursor_character": "pane",  # ft->wp
    "mouse_all_flag": "pane",  # ft->wp->base.mode MODE_MOUSE_ALL
    "mouse_any_flag": "pane",  # ft->wp->base.mode ALL_MOUSE_MODES
    "mouse_button_flag": "pane",  # ft->wp->base.mode MODE_MOUSE_BUTTON
    "mouse_sgr_flag": "pane",  # ft->wp->base.mode MODE_MOUSE_SGR
    "mouse_standard_flag": "pane",  # ft->wp->base.mode MODE_MOUSE_STANDARD
    "scroll_region_lower": "pane",  # ft->wp->base.rlower
    "scroll_region_upper": "pane",  # ft->wp->base.rupper
    "alternate_saved_x": "pane",  # ft->wp->base.saved_cx
    "alternate_saved_y": "pane",  # ft->wp->base.saved_cy
    "history_bytes": "pane",  # ft->wp
    "history_limit": "pane",  # ft->wp->base.grid->hlimit
    "history_size": "pane",  # ft->wp->base.grid->hsize
    "insert_flag": "pane",  # ft->wp->base.mode MODE_INSERT
    "keypad_cursor_flag": "pane",  # ft->wp->base.mode MODE_KCURSOR
    "keypad_flag": "pane",  # ft->wp->base.mode MODE_KKEYPAD
    "origin_flag": "pane",  # ft->wp->base.mode MODE_ORIGIN
    "wrap_flag": "pane",  # ft->wp->base.mode MODE_WRAP
    "active_window_index": "session",  # ft->s->curw->idx
    "last_window_index": "session",  # ft->s
    # tmux 3.7 pane-scope tokens that don't carry the pane_ prefix.
    "bracket_paste_flag": "pane",  # ft->wp->screen->mode MODE_BRACKETPASTE
    "synchronized_output_flag": "pane",  # ft->wp->base.mode MODE_SYNC
}


# Standalone tokens registered in tmux's ``format.c`` static table (the
# default tree of ``format_cb_*`` callbacks). They resolve in every
# ``list-*`` subcommand because their callbacks read process- or server-
# global state rather than dereferencing ``ft->c``, ``ft->s``, ``ft->wl``,
# or ``ft->wp``. Pane- and session-scoped standalones are routed via
# :data:`_SCOPE_OVERRIDES`; context-only tokens (registered outside
# ``format.c`` for a specific subcommand or mode) are routed via
# :data:`_CONTEXT_ONLY_TOKENS`.
_UNIVERSAL_TOKENS: frozenset[str] = frozenset(
    {
        "config_files",
        "host",
        "host_short",
        "line",
        "next_session_id",
        "pid",
        "socket_path",
        "start_time",
        "uid",
        "user",
        "version",
    }
)

# Tokens declared on :class:`Obj` whose callbacks are registered *outside*
# ``format.c``'s static table — i.e. they only resolve in a specific
# command context, not via ``format_defaults`` for any ``list-*``
# subcommand:
#
# - ``command_list_alias`` / ``command_list_name`` / ``command_list_usage``
#   → ``cmd-list-commands.c`` (the ``list-commands`` subcommand only).
# - ``search_match`` → ``window-copy.c`` (copy-mode pane formats only).
# - ``current_file`` → ``cfg.c`` (config parse context only).
#
# Emitting these in a ``list-sessions/windows/panes/clients/buffers`` ``-F``
# template is harmless (tmux renders unknown tokens to empty), but it
# misleads readers of the ``-F`` string about what the format engine will
# resolve in that scope. Routed to the ``"context"`` scope, which is
# explicitly excluded from every :data:`SCOPES_BY_LIST_CMD` entry.
_CONTEXT_ONLY_TOKENS: frozenset[str] = frozenset(
    {
        "command_list_alias",
        "command_list_name",
        "command_list_usage",
        "current_file",
        "search_match",
    }
)


def _token_scope(field_name: str) -> str:
    """Resolve a format token's scope from its name.

    Returns ``"universal"`` for cross-scope tokens (e.g. ``version``,
    ``socket_path``, ``host``). Returns ``"event"`` for runtime-only tokens
    that never appear in a ``list-*`` output (mouse, cursor, selection,
    popup). Returns ``"context"`` for tokens registered outside
    ``format.c``'s static table (only resolve in a specific command or
    mode context). Returns ``"pane"`` / ``"window"`` / ``"session"`` /
    ``"client"`` / ``"buffer"`` for scope-prefixed tokens.

    Fields that don't match any prefix, override, or known-token table
    fall back to ``"unknown"``. ``"unknown"`` is intentionally absent from
    every :data:`SCOPES_BY_LIST_CMD` entry, so an unclassified field is
    excluded from every ``list-*`` ``-F`` template — preventing a future
    untracked field from being silently emitted under a list command
    where it might crash older tmux. Add such a field to
    :data:`_SCOPE_OVERRIDES` (or the appropriate prefix / known-token
    table) to admit it.

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
    The override also corrects prefix-misclassified tokens — e.g.
    ``mouse_all_flag`` is a per-pane mode bit, not a runtime mouse event:

    >>> _token_scope("mouse_all_flag")
    'pane'
    >>> _token_scope("active_window_index")
    'session'

    Context-only tokens (registered outside ``format.c``'s static table)
    route to the ``"context"`` scope and are excluded from every
    ``list-*`` ``-F`` template:

    >>> _token_scope("command_list_alias")
    'context'
    >>> _token_scope("search_match")
    'context'

    Unclassified tokens fall back to ``"unknown"``, also excluded from
    every list command:

    >>> _token_scope("libtmux_test_nonexistent_token")
    'unknown'

    Notes
    -----
    Fields whose name doesn't carry one of the scope prefixes in
    :data:`_SCOPE_PREFIXES` (for example, ``bracket_paste_flag`` and
    ``synchronized_output_flag``, which are pane-scope but don't start
    with ``pane_``) MUST be classified via :data:`_SCOPE_OVERRIDES` —
    otherwise the fail-closed default returns ``"unknown"`` and
    excludes them from every ``list-*`` ``-F`` template. The drift
    catcher ``test_every_obj_field_classifies_to_known_scope`` enforces
    this on the base :class:`Obj`; subclasses that add custom fields
    must classify them via the same tables.
    """
    override = _SCOPE_OVERRIDES.get(field_name)
    if override is not None:
        return override
    for prefix, scope in _SCOPE_PREFIXES:
        if field_name.startswith(prefix):
            return scope
    if field_name in _CONTEXT_ONLY_TOKENS:
        return "context"
    if field_name in _UNIVERSAL_TOKENS:
        return "universal"
    return "unknown"


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
    """Dataclass of generic tmux object.

    Notes
    -----
    tmux may return fields from an object's active children along with the
    object itself. The practical consequence:

    - On a :class:`~libtmux.session.Session` row (``list-sessions``),
      every ``pane_*`` and ``window_*`` field resolves to the
      session's current window's **active pane** — *not* "the
      session's pane" (no such thing). ``session.active_window.window_id``
      and ``session.active_window.active_pane.pane_id`` are the
      canonical accessors for the same values.
    - On a :class:`~libtmux.window.Window` row (``list-windows``),
      every ``pane_*`` field resolves to that window's active pane.
    - On a :class:`~libtmux.client.Client` row (``list-clients``),
      every ``session_*``, ``window_*``, and ``pane_*`` field reflects
      the client's attached session, current window, and active pane.

    A reader who treats ``session.pane_id`` as the literal session's
    pane id (rather than "active pane of this session's current
    window") will be surprised when the active window changes.
    """

    server: Server

    active_window_index: str | None = None
    alternate_saved_x: str | None = None
    alternate_saved_y: str | None = None
    bracket_paste_flag: str | None = None
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
    pane_flags: str | None = None
    pane_floating_flag: str | None = None
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
    pane_pb_progress: str | None = None
    pane_pb_state: str | None = None
    pane_pid: str | None = None
    pane_pipe: str | None = None
    pane_pipe_pid: str | None = None
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
    pane_x: str | None = None
    pane_y: str | None = None
    pane_z: str | None = None
    pane_zoomed_flag: str | None = None
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
    synchronized_output_flag: str | None = None
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
        """Refresh dataclass fields from a single ``list-*`` row.

        Used by the public ``refresh()`` methods on :class:`~libtmux.Pane`,
        :class:`~libtmux.Window`, :class:`~libtmux.Session`, and
        :class:`~libtmux.Client`. Each subclass guards its identity field
        (``pane_id``, ``window_id``, ``session_id``, ``client_name``)
        against ``None`` before delegating here; this base method enforces
        the same precondition explicitly so the guarantee survives
        ``python -O``, where an ``assert`` would be stripped.

        Raises
        ------
        ValueError
            When ``obj_id`` is ``None``. Surfaces a clear error under
            ``python -O``, matching the contract of the public ``refresh()``
            methods.
        """
        if obj_id is None:
            msg = "Obj._refresh requires a non-None obj_id"
            raise ValueError(msg)
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
    >>> 'pane_id' in fields  # active pane for the listed session
    True
    >>> 'client_name' in fields  # upward not allowed
    False
    >>> 'server' in fields
    False

    Pane scope picks up window and session tokens too:

    >>> fields, _ = get_output_format("list-panes", "3.6a")
    >>> all(t in fields for t in ('pane_id', 'window_id', 'session_id'))
    True

    ``list-clients`` adds fields for the attached client:

    >>> fields, _ = get_output_format("list-clients", "3.6a")
    >>> 'client_name' in fields
    True
    >>> 'pane_id' in fields
    True
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

    Routes all commands through the server's engine, enabling:
    - Control mode persistent connection for fetch operations
    - Engine-specific validation (e.g., control_session preflight checks)
    - Consistent error handling across all tmux operations

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
        Filter expression evaluated by tmux (``-f`` flag). tmux omits rows
        whose expanded expression is false before libtmux parses the result.

        .. warning::

            tmux silently expands a malformed filter (unclosed ``#{...}``,
            unknown format token) to empty, which is treated as false —
            every row is suppressed and no stderr is emitted. A bad filter
            is indistinguishable from "filter matched nothing"; verify the
            expression against the FORMATS section of ``tmux(1)``. See
            :ref:`native-filtering` for the typed wrappers that share this
            caveat.

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

    if list_extra_args is not None and isinstance(list_extra_args, Iterable):
        cmd_args.extend(list(list_extra_args))

    if filter is not None:
        cmd_args.extend(["-f", filter])

    cmd_args.append(f"-F{format_string}")

    tmux_cmds = [
        list_cmd,
        *cmd_args,
    ]

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

    # Route through the server's engine via server.cmd()
    proc = server.cmd(list_cmd, *cmd_args)

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


def _is_target_not_found_error(stderr_text: str) -> bool:
    """Return True if tmux failed because the ``-t`` target does not exist.

    A live tmux server rejects an unknown target with ``can't find <kind>:
    <target>`` on stderr (``cmd_find_target`` in tmux's ``cmd-find.c``), for
    every object kind and every supported tmux version. Every *other* failure
    -- a stopped daemon, a missing socket, a permission error -- says something
    else, and stays a :exc:`~libtmux.exc.LibTmuxException`.

    This is the mirror image of :func:`libtmux.server._is_daemon_not_up_error`:
    together they answer "is the object gone, or is the server gone?" from the
    same stderr text.

    Parameters
    ----------
    stderr_text : str
        tmux's stderr, as carried by the raised
        :exc:`~libtmux.exc.LibTmuxException`.

    Returns
    -------
    bool
        True when the object named by ``-t`` does not exist on a reachable
        server.

    Examples
    --------
    >>> from libtmux.neo import _is_target_not_found_error
    >>> _is_target_not_found_error("can't find pane: %99")
    True
    >>> _is_target_not_found_error("can't find window: @99")
    True
    >>> _is_target_not_found_error("can't find session: $99")
    True

    A server that isn't there is a different answer:

    >>> _is_target_not_found_error("no server running on /tmp/tmux-1000/default")
    False
    >>> _is_target_not_found_error(
    ...     "error connecting to /tmp/tmux-1000/nope (No such file or directory)"
    ... )
    False
    """
    return "can't find " in stderr_text


def _best_winlink(rows: OutputsRaw) -> OutputRaw:
    """Pick the winlink row tmux would select.

    A ``list-windows`` listing enumerates :term:`winlinks <winlink>` --
    ``(session, index, window)`` edges -- not windows. ``link-window`` can attach
    one window to a session at several indexes at once, so the same
    ``window_id`` may appear on several rows, each with a different
    ``window_index``.

    tmux selects the current winlink when it contains the window, otherwise the
    first. ``#{window_active}`` identifies the current row, and the lowest
    ``window_index`` is tmux's first -- chosen explicitly here, so the caller
    need not pre-sort the rows.

    Parameters
    ----------
    rows : OutputsRaw
        Non-empty rows for one object id in one session. Order does not
        matter: the current winlink wins, otherwise the lowest
        ``window_index``.

    Returns
    -------
    OutputRaw
        The row naming the winlink tmux would act on.

    Examples
    --------
    One row is the whole answer:

    >>> from libtmux.neo import _best_winlink
    >>> _best_winlink([{"window_id": "@0", "window_index": "1"}])["window_index"]
    '1'

    A window linked into one session twice gives two rows. When the session is
    sitting on the higher-indexed link, that is the one tmux acts on:

    >>> _best_winlink([
    ...     {"window_id": "@0", "window_index": "1", "window_active": "0"},
    ...     {"window_id": "@0", "window_index": "5", "window_active": "1"},
    ... ])["window_index"]
    '5'

    When the session is sitting on some *other* window, neither link is current,
    and tmux falls back to the first:

    >>> _best_winlink([
    ...     {"window_id": "@0", "window_index": "1", "window_active": "0"},
    ...     {"window_id": "@0", "window_index": "5", "window_active": "0"},
    ... ])["window_index"]
    '1'

    The fallback reads the lowest index, not the first row, so a listing that
    happened to arrive high-index-first still answers tmux's first:

    >>> _best_winlink([
    ...     {"window_id": "@0", "window_index": "5", "window_active": "0"},
    ...     {"window_id": "@0", "window_index": "1", "window_active": "0"},
    ... ])["window_index"]
    '1'
    """
    if len(rows) == 1:
        return rows[0]

    for row in rows:
        if row.get("window_active") == "1":
            return row

    return min(rows, key=lambda row: int(row["window_index"]))


def fetch_obj(
    server: Server,
    obj_key: str,
    obj_id: str,
    list_cmd: ListCmd = "list-panes",
    list_extra_args: ListExtraArgs = None,
) -> OutputRaw:
    """Fetch the single ``list-*`` row whose *obj_key* equals *obj_id*.

    A listing enumerates :term:`winlinks <winlink>`, so a window linked into one
    session at two indexes matches twice. :func:`_best_winlink` then picks the
    row tmux itself would act on, rather than whichever sorted last.

    Parameters
    ----------
    server : :class:`~libtmux.server.Server`
        The tmux server to query.
    obj_key : str
        Identity field to match, e.g. ``"pane_id"``.
    obj_id : str
        Value the identity field must equal, e.g. ``"%3"``.
    list_cmd : ListCmd
        tmux list subcommand to run.
    list_extra_args : ListExtraArgs, optional
        Extra arguments appended verbatim to the tmux command, e.g.
        ``("-t", "%3")`` to scope the listing to one object's parent.

    Returns
    -------
    OutputRaw
        The matching row, as a dict of tmux format fields.

    Raises
    ------
    :exc:`~libtmux.exc.TmuxObjectDoesNotExist`
        When the object does not exist -- whether tmux said so on stderr
        (``can't find pane: %99``, for a ``-t``-scoped listing) or the object
        simply never appeared in the rows.
    :exc:`~libtmux.exc.LibTmuxException`
        For every other tmux failure, notably an unreachable server.

    Examples
    --------
    >>> from libtmux.neo import fetch_obj
    >>> fetch_obj(
    ...     server=pane.server,
    ...     obj_key="pane_id",
    ...     obj_id=pane.pane_id,
    ...     list_cmd="list-panes",
    ...     list_extra_args=("-t", pane.pane_id),
    ... )["pane_id"] == pane.pane_id
    True

    A pane that does not exist on a live server is a
    :exc:`~libtmux.exc.TmuxObjectDoesNotExist`, not a bare tmux error:

    >>> from libtmux import exc
    >>> try:
    ...     fetch_obj(
    ...         server=pane.server,
    ...         obj_key="pane_id",
    ...         obj_id="%99999",
    ...         list_cmd="list-panes",
    ...         list_extra_args=("-t", "%99999"),
    ...     )
    ... except exc.TmuxObjectDoesNotExist as e:
    ...     print(e)
    Could not find pane_id=%99999 for list-panes ('-t', '%99999')
    """
    try:
        obj_formatters_filtered = fetch_objs(
            server=server,
            list_cmd=list_cmd,
            list_extra_args=list_extra_args,
        )
    except exc.LibTmuxException as e:
        # A ``-t``-scoped listing pushes the "does it exist?" question down
        # into tmux, which answers on stderr rather than with an empty listing.
        # Re-raise those as the same TmuxObjectDoesNotExist an unscoped listing
        # would have produced; anything else (a dead server) keeps propagating.
        if not _is_target_not_found_error(str(e)):
            raise
        raise exc.TmuxObjectDoesNotExist(
            obj_key=obj_key,
            obj_id=obj_id,
            list_cmd=list_cmd,
            list_extra_args=list_extra_args,
        ) from e

    matches = [row for row in obj_formatters_filtered if row.get(obj_key) == obj_id]

    if not matches:
        raise exc.TmuxObjectDoesNotExist(
            obj_key=obj_key,
            obj_id=obj_id,
            list_cmd=list_cmd,
            list_extra_args=list_extra_args,
        )

    return _best_winlink(matches)
