"""Internal constants."""

from __future__ import annotations

import io
import logging
import typing as t
from dataclasses import dataclass, field

from libtmux._internal.dataclasses import SkipDefaultFieldsReprMixin
from libtmux._internal.sparse_array import SparseArray, is_sparse_array_list

if t.TYPE_CHECKING:
    from typing import TypeAlias


T = t.TypeVar("T")

TerminalFeatures = dict[str, list[str]]
HookArray: TypeAlias = "dict[str, SparseArray[str]]"

logger = logging.getLogger(__name__)


@dataclass(repr=False)
class ServerOptions(
    SkipDefaultFieldsReprMixin,
):
    """Container for tmux server options."""

    backspace: str | None = field(default=None)
    buffer_limit: int | None = field(default=None)
    command_alias: SparseArray[str] = field(default_factory=SparseArray)
    default_terminal: str | None = field(default=None)
    copy_command: str | None = field(default=None)
    escape_time: int | None = field(default=None)
    editor: str | None = field(default=None)
    exit_empty: t.Literal["on", "off"] | None = field(default=None)
    exit_unattached: t.Literal["on", "off"] | None = field(default=None)
    extended_keys: t.Literal["on", "off", "always"] | None = field(default=None)
    focus_events: t.Literal["on", "off"] | None = field(default=None)
    history_file: str | None = field(default=None)
    message_limit: int | None = field(default=None)
    prompt_history_limit: int | None = field(default=None)
    set_clipboard: t.Literal["on", "external", "off"] | None = field(default=None)
    terminal_features: TerminalFeatures = field(default_factory=dict)
    terminal_overrides: SparseArray[str] = field(default_factory=SparseArray)
    user_keys: SparseArray[str] = field(default_factory=SparseArray)
    # tmux 3.5+ options
    default_client_command: str | None = field(default=None)
    extended_keys_format: t.Literal["csi-u", "xterm"] | None = field(default=None)

    def __init__(self, **kwargs: object) -> None:
        # Convert hyphenated keys to underscored attribute names and assign values
        for key, value in kwargs.items():
            key_underscored = key.replace("-", "_")
            setattr(self, key_underscored, value)


@dataclass(repr=False)
class SessionOptions(
    SkipDefaultFieldsReprMixin,
):
    """Container for tmux session options."""

    activity_action: t.Literal["any", "none", "current", "other"] | None = field(
        default=None,
    )
    assume_paste_time: int | None = field(default=None)
    base_index: int | None = field(default=None)
    bell_action: t.Literal["any", "none", "current", "other"] | None = field(
        default=None,
    )
    default_command: str | None = field(default=None)
    default_shell: str | None = field(default=None)
    default_size: str | None = field(default=None)  # Format "XxY"
    destroy_unattached: t.Literal["on", "off"] | None = field(default=None)
    detach_on_destroy: (
        t.Literal["off", "on", "no-detached", "previous", "next"] | None
    ) = field(default=None)
    display_panes_active_colour: str | None = field(default=None)
    display_panes_colour: str | None = field(default=None)
    display_panes_time: int | None = field(default=None)
    display_time: int | None = field(default=None)
    history_limit: int | None = field(default=None)
    key_table: str | None = field(default=None)
    lock_after_time: int | None = field(default=None)
    lock_command: str | None = field(default=None)
    menu_style: str | None = field(default=None)
    menu_selected_style: str | None = field(default=None)
    menu_border_style: str | None = field(default=None)
    menu_border_lines: (
        t.Literal["single", "rounded", "double", "heavy", "simple", "padded", "none"]
        | None
    ) = field(default=None)
    message_command_style: str | None = field(default=None)
    message_line: int | None = field(default=None)
    message_style: str | None = field(default=None)
    mouse: t.Literal["on", "off"] | None = field(default=None)
    prefix: str | None = field(default=None)
    prefix2: str | None = field(default=None)
    renumber_windows: t.Literal["on", "off"] | None = field(default=None)
    repeat_time: int | None = field(default=None)
    set_titles: t.Literal["on", "off"] | None = field(default=None)
    set_titles_string: str | None = field(default=None)
    silence_action: t.Literal["any", "none", "current", "other"] | None = field(
        default=None,
    )
    status: t.Literal["off", "on"] | int | None = field(default=None)
    status_format: list[str] | None = field(default=None)
    status_interval: int | None = field(default=None)
    status_justify: t.Literal["left", "centre", "right", "absolute-centre"] | None = (
        field(default=None)
    )
    status_keys: t.Literal["vi", "emacs"] | None = field(default=None)
    status_left: str | None = field(default=None)
    status_left_length: int | None = field(default=None)
    status_left_style: str | None = field(default=None)
    status_position: t.Literal["top", "bottom"] | None = field(default=None)
    status_right: str | None = field(default=None)
    status_right_length: int | None = field(default=None)
    status_right_style: str | None = field(default=None)
    status_style: str | None = field(default=None)
    update_environment: SparseArray[str] = field(default_factory=SparseArray)
    visual_activity: t.Literal["on", "off", "both"] | None = field(default=None)
    visual_bell: t.Literal["on", "off", "both"] | None = field(default=None)
    visual_silence: t.Literal["on", "off", "both"] | None = field(default=None)
    word_separators: str | None = field(default=None)

    def __init__(self, **kwargs: object) -> None:
        # Convert hyphenated keys to underscored attribute names and assign values
        for key, value in kwargs.items():
            key_underscored = key.replace("-", "_")
            setattr(self, key_underscored, value)


@dataclass(repr=False)
class WindowOptions(
    SkipDefaultFieldsReprMixin,
):
    """Container for tmux window options."""

    aggressive_resize: t.Literal["on", "off"] | None = field(default=None)
    automatic_rename: t.Literal["on", "off"] | None = field(default=None)
    automatic_rename_format: str | None = field(default=None)
    clock_mode_colour: str | None = field(default=None)
    clock_mode_style: t.Literal["12", "24"] | None = field(default=None)
    fill_character: str | None = field(default=None)
    main_pane_height: int | str | None = field(default=None)
    main_pane_width: int | str | None = field(default=None)
    copy_mode_match_style: str | None = field(default=None)
    copy_mode_mark_style: str | None = field(default=None)
    copy_mode_current_match_style: str | None = field(default=None)
    mode_keys: t.Literal["vi", "emacs"] | None = field(default=None)
    mode_style: str | None = field(default=None)
    monitor_activity: t.Literal["on", "off"] | None = field(default=None)
    monitor_bell: t.Literal["on", "off"] | None = field(default=None)
    monitor_silence: int | None = field(default=None)  # Assuming seconds as int
    other_pane_height: int | str | None = field(default=None)
    other_pane_width: int | str | None = field(default=None)
    pane_active_border_style: str | None = field(default=None)
    pane_base_index: int | None = field(default=None)
    pane_border_format: str | None = field(default=None)
    pane_border_indicators: t.Literal["off", "colour", "arrows", "both"] | None = field(
        default=None,
    )
    pane_border_lines: (
        t.Literal["single", "double", "heavy", "simple", "number"] | None
    ) = field(default=None)
    pane_border_status: t.Literal["off", "top", "bottom"] | None = field(
        default=None,
    )
    pane_border_style: str | None = field(default=None)
    popup_style: str | None = field(default=None)
    popup_border_style: str | None = field(default=None)
    popup_border_lines: (
        t.Literal["single", "rounded", "double", "heavy", "simple", "padded", "none"]
        | None
    ) = field(default=None)
    window_status_activity_style: str | None = field(default=None)
    window_status_bell_style: str | None = field(default=None)
    window_status_current_format: str | None = field(default=None)
    window_status_current_style: str | None = field(default=None)
    window_status_format: str | None = field(default=None)
    window_status_last_style: str | None = field(default=None)
    window_status_separator: str | None = field(default=None)
    window_status_style: str | None = field(default=None)
    window_size: t.Literal["largest", "smallest", "manual", "latest"] | None = field(
        default=None,
    )
    wrap_search: t.Literal["on", "off"] | None = field(default=None)
    # tmux 3.5+ options
    tiled_layout_max_columns: int | None = field(default=None)

    def __init__(self, **kwargs: object) -> None:
        # Convert hyphenated keys to underscored attribute names and assign values
        for key, value in kwargs.items():
            key_underscored = key.replace("-", "_")
            setattr(self, key_underscored, value)


@dataclass(repr=False)
class PaneOptions(
    SkipDefaultFieldsReprMixin,
):
    """Container for tmux pane options."""

    allow_passthrough: t.Literal["on", "off", "all"] | None = field(default=None)
    allow_rename: t.Literal["on", "off"] | None = field(default=None)
    alternate_screen: t.Literal["on", "off"] | None = field(default=None)
    cursor_colour: str | None = field(default=None)
    pane_colours: list[str] | None = field(default=None)
    cursor_style: (
        t.Literal[
            "default",
            "blinking-block",
            "block",
            "blinking-underline",
            "underline",
            "blinking-bar",
            "bar",
        ]
        | None
    ) = field(default=None)
    remain_on_exit: t.Literal["on", "off", "failed"] | None = field(default=None)
    remain_on_exit_format: str | None = field(default=None)
    scroll_on_clear: t.Literal["on", "off"] | None = field(default=None)
    synchronize_panes: t.Literal["on", "off"] | None = field(default=None)
    window_active_style: str | None = field(default=None)
    window_style: str | None = field(default=None)
    # tmux 3.5+ options
    pane_scrollbars: t.Literal["off", "modal", "on"] | None = field(default=None)
    pane_scrollbars_style: str | None = field(default=None)

    def __init__(self, **kwargs: object) -> None:
        # Convert hyphenated keys to underscored attribute names and assign values
        for key, value in kwargs.items():
            key_underscored = key.replace("-", "_")
            setattr(self, key_underscored, value)


@dataclass(repr=False)
class Options(
    ServerOptions,
    SessionOptions,
    WindowOptions,
    PaneOptions,
    SkipDefaultFieldsReprMixin,
):
    """Container for all tmux options (server, session, window, and pane)."""

    def __init__(self, **kwargs: object) -> None:
        # Convert hyphenated keys to underscored attribute names and assign values
        # Remove asaterisk from inherited options
        for key, value in kwargs.items():
            key_underscored = key.replace("-", "_")
            key_asterisk_removed = key_underscored.rstrip("*")
            setattr(self, key_asterisk_removed, value)


@dataclass(repr=False)
class Hooks(
    SkipDefaultFieldsReprMixin,
):
    """tmux hooks data structure.

    Parses tmux hook output into typed :class:`SparseArray` fields, preserving
    array indices for hooks that can have multiple commands at different indices.

    Examples
    --------
    Parse raw tmux hook output:

    >>> from libtmux._internal.constants import Hooks

    >>> raw = [
    ...     "session-renamed[0] set-option -g status-left-style bg=red",
    ...     "session-renamed[1] display-message 'session renamed'",
    ... ]
    >>> hooks = Hooks.from_stdout(raw)

    Access individual hook commands by index:

    >>> hooks.session_renamed[0]
    'set-option -g status-left-style bg=red'
    >>> hooks.session_renamed[1]
    "display-message 'session renamed'"

    Get all commands as a list (sorted by index):

    >>> hooks.session_renamed.as_list()
    ['set-option -g status-left-style bg=red', "display-message 'session renamed'"]

    Sparse indices are preserved (gaps in index numbers):

    >>> raw_sparse = [
    ...     "pane-focus-in[0] refresh-client",
    ...     "pane-focus-in[5] display-message 'focus'",
    ... ]
    >>> hooks_sparse = Hooks.from_stdout(raw_sparse)
    >>> 0 in hooks_sparse.pane_focus_in
    True
    >>> 5 in hooks_sparse.pane_focus_in
    True
    >>> 3 in hooks_sparse.pane_focus_in
    False
    >>> sorted(hooks_sparse.pane_focus_in.keys())
    [0, 5]

    Iterate over values in index order:

    >>> for cmd in hooks_sparse.pane_focus_in.iter_values():
    ...     print(cmd)
    refresh-client
    display-message 'focus'

    Multiple hook types in one parse:

    >>> raw_multi = [
    ...     "after-new-window[0] select-pane -t 0",
    ...     "after-new-window[1] send-keys 'clear' Enter",
    ...     "window-renamed[0] refresh-client -S",
    ... ]
    >>> hooks_multi = Hooks.from_stdout(raw_multi)
    >>> len(hooks_multi.after_new_window)
    2
    >>> len(hooks_multi.window_renamed)
    1
    """

    # --- Tmux normal hooks ---
    # Run when a window has activity. See monitor-activity.
    alert_activity: SparseArray[str] = field(default_factory=SparseArray)
    # Run when a window has received a bell. See monitor-bell.
    alert_bell: SparseArray[str] = field(default_factory=SparseArray)
    # Run when a window has been silent. See monitor-silence.
    alert_silence: SparseArray[str] = field(default_factory=SparseArray)
    # Run when a client becomes the latest active client of its session.
    client_active: SparseArray[str] = field(default_factory=SparseArray)
    # Run when a client is attached.
    client_attached: SparseArray[str] = field(default_factory=SparseArray)
    # Run when a client is detached.
    client_detached: SparseArray[str] = field(default_factory=SparseArray)
    # Run when focus enters a client.
    client_focus_in: SparseArray[str] = field(default_factory=SparseArray)
    # Run when focus exits a client.
    client_focus_out: SparseArray[str] = field(default_factory=SparseArray)
    # Run when a client is resized.
    client_resized: SparseArray[str] = field(default_factory=SparseArray)
    # Run when a client's attached session is changed.
    client_session_changed: SparseArray[str] = field(default_factory=SparseArray)
    # Run when the program running in a pane exits, but remain-on-exit is on so the pane
    # has not closed.
    pane_died: SparseArray[str] = field(default_factory=SparseArray)
    # Run when the program running in a pane exits.
    pane_exited: SparseArray[str] = field(default_factory=SparseArray)
    # Run when the focus enters a pane, if the focus-events option is on.
    pane_focus_in: SparseArray[str] = field(default_factory=SparseArray)
    # Run when the focus exits a pane, if the focus-events option is on.
    pane_focus_out: SparseArray[str] = field(default_factory=SparseArray)
    # Run when the terminal clipboard is set using the xterm(1) escape sequence.
    pane_set_clipboard: SparseArray[str] = field(default_factory=SparseArray)
    # Run when a new session created.
    session_created: SparseArray[str] = field(default_factory=SparseArray)
    # Run when a session closed.
    session_closed: SparseArray[str] = field(default_factory=SparseArray)
    # Run when a session is renamed.
    session_renamed: SparseArray[str] = field(default_factory=SparseArray)
    # Run when a window is linked into a session.
    window_linked: SparseArray[str] = field(default_factory=SparseArray)
    # Run when a window is renamed.
    window_renamed: SparseArray[str] = field(default_factory=SparseArray)
    # Run when a window is resized. This may be after the client-resized hook is run.
    window_resized: SparseArray[str] = field(default_factory=SparseArray)
    # Run when a window is unlinked from a session.
    window_unlinked: SparseArray[str] = field(default_factory=SparseArray)
    # Run when a pane title changes (tmux 3.5+)
    pane_title_changed: SparseArray[str] = field(default_factory=SparseArray)
    # Run when terminal reports a light theme (tmux 3.5+)
    client_light_theme: SparseArray[str] = field(default_factory=SparseArray)
    # Run when terminal reports a dark theme (tmux 3.5+)
    client_dark_theme: SparseArray[str] = field(default_factory=SparseArray)

    # --- Tmux control mode hooks ---
    # The client has detached.
    client_detached_control: SparseArray[str] = field(default_factory=SparseArray)
    # The client is now attached to the session with ID session-id, which is named name.
    client_session_changed_control: SparseArray[str] = field(
        default_factory=SparseArray,
    )
    # An error has happened in a configuration file.
    config_error: SparseArray[str] = field(default_factory=SparseArray)
    # The pane has been continued after being paused (if the pause-after flag is set,
    # see refresh-client -A).
    continue_control: SparseArray[str] = field(default_factory=SparseArray)
    # The tmux client is exiting immediately, either because it is not attached to any
    # session or an error occurred.
    exit_control: SparseArray[str] = field(default_factory=SparseArray)
    # New form of %output sent when the pause-after flag is set.
    extended_output: SparseArray[str] = field(default_factory=SparseArray)
    # The layout of a window with ID window-id changed.
    layout_change: SparseArray[str] = field(default_factory=SparseArray)
    # A message sent with the display-message command.
    message_control: SparseArray[str] = field(default_factory=SparseArray)
    # A window pane produced output.
    output: SparseArray[str] = field(default_factory=SparseArray)
    # The pane with ID pane-id has changed mode.
    pane_mode_changed: SparseArray[str] = field(default_factory=SparseArray)
    # Paste buffer name has been changed.
    paste_buffer_changed: SparseArray[str] = field(default_factory=SparseArray)
    # Paste buffer name has been deleted.
    paste_buffer_deleted: SparseArray[str] = field(default_factory=SparseArray)
    # The pane has been paused (if the pause-after flag is set).
    pause_control: SparseArray[str] = field(default_factory=SparseArray)
    # The client is now attached to the session with ID session-id, which is named name.
    session_changed_control: SparseArray[str] = field(default_factory=SparseArray)
    # The current session was renamed to name.
    session_renamed_control: SparseArray[str] = field(default_factory=SparseArray)
    # The session with ID session-id changed its active window to the window with ID
    # window-id.
    session_window_changed: SparseArray[str] = field(default_factory=SparseArray)
    # A session was created or destroyed.
    sessions_changed: SparseArray[str] = field(default_factory=SparseArray)
    # The value of the format associated with subscription name has changed to value.
    subscription_changed: SparseArray[str] = field(default_factory=SparseArray)
    # The window with ID window-id was created but is not linked to the current session.
    unlinked_window_add: SparseArray[str] = field(default_factory=SparseArray)
    # The window with ID window-id, which is not linked to the current session, was
    # closed.
    unlinked_window_close: SparseArray[str] = field(default_factory=SparseArray)
    # The window with ID window-id, which is not linked to the current session, was
    # renamed.
    unlinked_window_renamed: SparseArray[str] = field(default_factory=SparseArray)
    # The window with ID window-id was linked to the current session.
    window_add: SparseArray[str] = field(default_factory=SparseArray)
    # The window with ID window-id closed.
    window_close: SparseArray[str] = field(default_factory=SparseArray)
    # The layout of a window with ID window-id changed. The new layout is window-layout.
    # The window's visible layout is window-visible-layout and the window flags are
    # window-flags.
    window_layout_changed: SparseArray[str] = field(default_factory=SparseArray)
    # The active pane in the window with ID window-id changed to the pane with ID
    # pane-id.
    window_pane_changed: SparseArray[str] = field(default_factory=SparseArray)
    # The window with ID window-id was renamed to name.
    window_renamed_control: SparseArray[str] = field(default_factory=SparseArray)

    # --- After hooks - Run after specific tmux commands complete ---
    # Runs after 'bind-key' completes
    after_bind_key: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'capture-pane' completes
    after_capture_pane: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'copy-mode' completes
    after_copy_mode: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'display-message' completes
    after_display_message: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'display-panes' completes
    after_display_panes: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'kill-pane' completes
    after_kill_pane: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'list-buffers' completes
    after_list_buffers: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'list-clients' completes
    after_list_clients: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'list-keys' completes
    after_list_keys: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'list-panes' completes
    after_list_panes: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'list-sessions' completes
    after_list_sessions: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'list-windows' completes
    after_list_windows: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'load-buffer' completes
    after_load_buffer: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'lock-server' completes
    after_lock_server: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'new-session' completes
    after_new_session: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'new-window' completes
    after_new_window: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'paste-buffer' completes
    after_paste_buffer: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'pipe-pane' completes
    after_pipe_pane: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'queue' command is processed
    after_queue: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'refresh-client' completes
    after_refresh_client: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'rename-session' completes
    after_rename_session: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'rename-window' completes
    after_rename_window: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'resize-pane' completes
    after_resize_pane: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'resize-window' completes
    after_resize_window: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'save-buffer' completes
    after_save_buffer: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'select-layout' completes
    after_select_layout: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'select-pane' completes
    after_select_pane: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'select-window' completes
    after_select_window: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'send-keys' completes
    after_send_keys: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'set-buffer' completes
    after_set_buffer: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'set-environment' completes
    after_set_environment: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'set-hook' completes
    after_set_hook: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'set-option' completes
    after_set_option: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'show-environment' completes
    after_show_environment: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'show-messages' completes
    after_show_messages: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'show-options' completes
    after_show_options: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'split-window' completes
    after_split_window: SparseArray[str] = field(default_factory=SparseArray)
    # Runs after 'unbind-key' completes
    after_unbind_key: SparseArray[str] = field(default_factory=SparseArray)
    # Runs when a command fails (tmux 3.5+)
    command_error: SparseArray[str] = field(default_factory=SparseArray)

    @classmethod
    def from_stdout(cls, value: list[str]) -> Hooks:
        """Parse raw tmux hook output into a Hooks instance.

        The parsing pipeline:

        1. ``parse_options_to_dict()`` - Parse "key value" lines into dict
        2. ``explode_arrays(force_array=True)`` - Extract array indices into SparseArray
        3. ``explode_complex()`` - Handle complex option types
        4. Rename keys: ``session-renamed`` → ``session_renamed``

        Parameters
        ----------
        value : list[str]
            Raw tmux output lines from ``show-hooks`` command.

        Returns
        -------
        Hooks
            Parsed hooks with SparseArray fields for each hook type.

        Examples
        --------
        Basic parsing:

        >>> from libtmux._internal.constants import Hooks

        >>> raw = ["session-renamed[0] display-message 'renamed'"]
        >>> hooks = Hooks.from_stdout(raw)
        >>> hooks.session_renamed[0]
        "display-message 'renamed'"

        The pipeline preserves sparse indices:

        >>> raw = [
        ...     "after-select-window[0] refresh-client",
        ...     "after-select-window[10] display-message 'selected'",
        ... ]
        >>> hooks = Hooks.from_stdout(raw)
        >>> sorted(hooks.after_select_window.keys())
        [0, 10]

        Empty input returns empty SparseArrays:

        >>> hooks_empty = Hooks.from_stdout([])
        >>> len(hooks_empty.session_renamed)
        0
        >>> hooks_empty.session_renamed.as_list()
        []
        """
        from libtmux.options import (
            explode_arrays,
            explode_complex,
            parse_options_to_dict,
        )

        output_exploded = explode_complex(
            explode_arrays(
                parse_options_to_dict(
                    io.StringIO("\n".join(value)),
                ),
                force_array=True,
            ),
        )

        assert is_sparse_array_list(output_exploded)

        output_renamed: HookArray = {
            k.lstrip("%").replace("-", "_"): v for k, v in output_exploded.items()
        }

        return cls(**output_renamed)
