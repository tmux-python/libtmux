"""Internal constants."""

import io
import logging
import typing as t
from dataclasses import dataclass, field

from libtmux._internal.dataclasses import SkipDefaultFieldsReprMixin

if t.TYPE_CHECKING:
    from typing_extensions import TypeAlias, TypeGuard

    from libtmux.options import ExplodedComplexUntypedOptionsDict

T = t.TypeVar("T")

TerminalFeatures = t.Dict[str, t.List[str]]
HookArray: "TypeAlias" = "t.Dict[str, TmuxArray[str]]"

logger = logging.getLogger(__name__)


def is_tmux_array_list(
    items: "ExplodedComplexUntypedOptionsDict",
) -> "TypeGuard[HookArray]":
    return all(
        isinstance(
            v,
            TmuxArray,
        )
        for k, v in items.items()
    )


class TmuxArray(t.Dict[int, T], t.Generic[T]):
    """Support non-sequential indexes without raising IndexError."""

    def add(self, index: int, value: T) -> None:
        self[index] = value

    def append(self, value: T) -> None:
        index = max(self.keys()) + 1
        self[index] = value

    def iter_values(self) -> t.Iterator[T]:
        for index in sorted(self.keys()):
            yield self[index]

    def as_list(self) -> t.List[T]:
        return [self[index] for index in sorted(self.keys())]


@dataclass(repr=False)
class ServerOptions(
    SkipDefaultFieldsReprMixin,
):
    backspace: t.Optional[str] = field(default=None)
    buffer_limit: t.Optional[int] = field(default=None)
    command_alias: TmuxArray[str] = field(default_factory=TmuxArray)
    default_terminal: t.Optional[str] = field(default=None)
    copy_command: t.Optional[str] = field(default=None)
    escape_time: t.Optional[int] = field(default=None)
    editor: t.Optional[str] = field(default=None)
    exit_empty: t.Optional[t.Literal["on", "off"]] = field(default=None)
    exit_unattached: t.Optional[t.Literal["on", "off"]] = field(default=None)
    extended_keys: t.Optional[t.Literal["on", "off", "always"]] = field(default=None)
    focus_events: t.Optional[t.Literal["on", "off"]] = field(default=None)
    history_file: t.Optional[str] = field(default=None)
    message_limit: t.Optional[int] = field(default=None)
    prompt_history_limit: t.Optional[int] = field(default=None)
    set_clipboard: t.Optional[t.Literal["on", "external", "off"]] = field(default=None)
    terminal_features: TerminalFeatures = field(default_factory=dict)
    terminal_overrides: TmuxArray[str] = field(default_factory=TmuxArray)
    user_keys: TmuxArray[str] = field(default_factory=TmuxArray)

    def __init__(self, **kwargs: object) -> None:
        # Convert hyphenated keys to underscored attribute names and assign values
        for key, value in kwargs.items():
            key_underscored = key.replace("-", "_")
            setattr(self, key_underscored, value)


@dataclass(repr=False)
class SessionOptions(
    SkipDefaultFieldsReprMixin,
):
    activity_action: t.Optional[t.Literal["any", "none", "current", "other"]] = field(
        default=None,
    )
    assume_paste_time: t.Optional[int] = field(default=None)
    base_index: t.Optional[int] = field(default=None)
    bell_action: t.Optional[t.Literal["any", "none", "current", "other"]] = field(
        default=None,
    )
    default_command: t.Optional[str] = field(default=None)
    default_shell: t.Optional[str] = field(default=None)
    default_size: t.Optional[str] = field(default=None)  # Format "XxY"
    destroy_unattached: t.Optional[t.Literal["on", "off"]] = field(default=None)
    detach_on_destroy: t.Optional[
        t.Literal["off", "on", "no-detached", "previous", "next"]
    ] = field(default=None)
    display_panes_active_colour: t.Optional[str] = field(default=None)
    display_panes_colour: t.Optional[str] = field(default=None)
    display_panes_time: t.Optional[int] = field(default=None)
    display_time: t.Optional[int] = field(default=None)
    history_limit: t.Optional[int] = field(default=None)
    key_table: t.Optional[str] = field(default=None)
    lock_after_time: t.Optional[int] = field(default=None)
    lock_command: t.Optional[str] = field(default=None)
    menu_style: t.Optional[str] = field(default=None)
    menu_selected_style: t.Optional[str] = field(default=None)
    menu_border_style: t.Optional[str] = field(default=None)
    menu_border_lines: t.Optional[
        t.Literal["single", "rounded", "double", "heavy", "simple", "padded", "none"]
    ] = field(default=None)
    message_command_style: t.Optional[str] = field(default=None)
    message_line: t.Optional[int] = field(default=None)
    message_style: t.Optional[str] = field(default=None)
    mouse: t.Optional[t.Literal["on", "off"]] = field(default=None)
    prefix: t.Optional[str] = field(default=None)
    prefix2: t.Optional[str] = field(default=None)
    renumber_windows: t.Optional[t.Literal["on", "off"]] = field(default=None)
    repeat_time: t.Optional[int] = field(default=None)
    set_titles: t.Optional[t.Literal["on", "off"]] = field(default=None)
    set_titles_string: t.Optional[str] = field(default=None)
    silence_action: t.Optional[t.Literal["any", "none", "current", "other"]] = field(
        default=None,
    )
    status: t.Optional[t.Union[t.Literal["off", "on"], int]] = field(default=None)
    status_format: t.Optional[t.List[str]] = field(default=None)
    status_interval: t.Optional[int] = field(default=None)
    status_justify: t.Optional[
        t.Literal["left", "centre", "right", "absolute-centre"]
    ] = field(default=None)
    status_keys: t.Optional[t.Literal["vi", "emacs"]] = field(default=None)
    status_left: t.Optional[str] = field(default=None)
    status_left_length: t.Optional[int] = field(default=None)
    status_left_style: t.Optional[str] = field(default=None)
    status_position: t.Optional[t.Literal["top", "bottom"]] = field(default=None)
    status_right: t.Optional[str] = field(default=None)
    status_right_length: t.Optional[int] = field(default=None)
    status_right_style: t.Optional[str] = field(default=None)
    status_style: t.Optional[str] = field(default=None)
    update_environment: TmuxArray[str] = field(default_factory=TmuxArray)
    visual_activity: t.Optional[t.Literal["on", "off", "both"]] = field(default=None)
    visual_bell: t.Optional[t.Literal["on", "off", "both"]] = field(default=None)
    visual_silence: t.Optional[t.Literal["on", "off", "both"]] = field(default=None)
    word_separators: t.Optional[str] = field(default=None)

    def __init__(self, **kwargs: object) -> None:
        # Convert hyphenated keys to underscored attribute names and assign values
        for key, value in kwargs.items():
            key_underscored = key.replace("-", "_")
            setattr(self, key_underscored, value)


@dataclass(repr=False)
class WindowOptions(
    SkipDefaultFieldsReprMixin,
):
    aggressive_resize: t.Optional[t.Literal["on", "off"]] = field(default=None)
    automatic_rename: t.Optional[t.Literal["on", "off"]] = field(default=None)
    automatic_rename_format: t.Optional[str] = field(default=None)
    clock_mode_colour: t.Optional[str] = field(default=None)
    clock_mode_style: t.Optional[t.Literal["12", "24"]] = field(default=None)
    fill_character: t.Optional[str] = field(default=None)
    main_pane_height: t.Optional[t.Union[int, str]] = field(default=None)
    main_pane_width: t.Optional[t.Union[int, str]] = field(default=None)
    copy_mode_match_style: t.Optional[str] = field(default=None)
    copy_mode_mark_style: t.Optional[str] = field(default=None)
    copy_mode_current_match_style: t.Optional[str] = field(default=None)
    mode_keys: t.Optional[t.Literal["vi", "emacs"]] = field(default=None)
    mode_style: t.Optional[str] = field(default=None)
    monitor_activity: t.Optional[t.Literal["on", "off"]] = field(default=None)
    monitor_bell: t.Optional[t.Literal["on", "off"]] = field(default=None)
    monitor_silence: t.Optional[int] = field(default=None)  # Assuming seconds as int
    other_pane_height: t.Optional[t.Union[int, str]] = field(default=None)
    other_pane_width: t.Optional[t.Union[int, str]] = field(default=None)
    pane_active_border_style: t.Optional[str] = field(default=None)
    pane_base_index: t.Optional[int] = field(default=None)
    pane_border_format: t.Optional[str] = field(default=None)
    pane_border_indicators: t.Optional[t.Literal["off", "colour", "arrows", "both"]] = (
        field(default=None)
    )
    pane_border_lines: t.Optional[
        t.Literal["single", "double", "heavy", "simple", "number"]
    ] = field(default=None)
    pane_border_status: t.Optional[t.Literal["off", "top", "bottom"]] = field(
        default=None,
    )
    pane_border_style: t.Optional[str] = field(default=None)
    popup_style: t.Optional[str] = field(default=None)
    popup_border_style: t.Optional[str] = field(default=None)
    popup_border_lines: t.Optional[
        t.Literal["single", "rounded", "double", "heavy", "simple", "padded", "none"]
    ] = field(default=None)
    window_status_activity_style: t.Optional[str] = field(default=None)
    window_status_bell_style: t.Optional[str] = field(default=None)
    window_status_current_format: t.Optional[str] = field(default=None)
    window_status_current_style: t.Optional[str] = field(default=None)
    window_status_format: t.Optional[str] = field(default=None)
    window_status_last_style: t.Optional[str] = field(default=None)
    window_status_separator: t.Optional[str] = field(default=None)
    window_status_style: t.Optional[str] = field(default=None)
    window_size: t.Optional[t.Literal["largest", "smallest", "manual", "latest"]] = (
        field(default=None)
    )
    wrap_search: t.Optional[t.Literal["on", "off"]] = field(default=None)

    def __init__(self, **kwargs: object) -> None:
        # Convert hyphenated keys to underscored attribute names and assign values
        for key, value in kwargs.items():
            key_underscored = key.replace("-", "_")
            setattr(self, key_underscored, value)


@dataclass(repr=False)
class PaneOptions(
    SkipDefaultFieldsReprMixin,
):
    allow_passthrough: t.Optional[t.Literal["on", "off", "all"]] = field(default=None)
    allow_rename: t.Optional[t.Literal["on", "off"]] = field(default=None)
    alternate_screen: t.Optional[t.Literal["on", "off"]] = field(default=None)
    cursor_colour: t.Optional[str] = field(default=None)
    pane_colours: t.Optional[t.List[str]] = field(default=None)
    cursor_style: t.Optional[
        t.Literal[
            "default",
            "blinking-block",
            "block",
            "blinking-underline",
            "underline",
            "blinking-bar",
            "bar",
        ]
    ] = field(default=None)
    remain_on_exit: t.Optional[t.Literal["on", "off", "failed"]] = field(default=None)
    remain_on_exit_format: t.Optional[str] = field(default=None)
    scroll_on_clear: t.Optional[t.Literal["on", "off"]] = field(default=None)
    synchronize_panes: t.Optional[t.Literal["on", "off"]] = field(default=None)
    window_active_style: t.Optional[str] = field(default=None)
    window_style: t.Optional[str] = field(default=None)

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
    """tmux hooks data structure."""

    # --- Tmux normal hooks ---
    # Run when a window has activity. See monitor-activity.
    alert_activity: TmuxArray[str] = field(default_factory=TmuxArray)
    # Run when a window has received a bell. See monitor-bell.
    alert_bell: TmuxArray[str] = field(default_factory=TmuxArray)
    # Run when a window has been silent. See monitor-silence.
    alert_silence: TmuxArray[str] = field(default_factory=TmuxArray)
    # Run when a client becomes the latest active client of its session.
    client_active: TmuxArray[str] = field(default_factory=TmuxArray)
    # Run when a client is attached.
    client_attached: TmuxArray[str] = field(default_factory=TmuxArray)
    # Run when a client is detached.
    client_detached: TmuxArray[str] = field(default_factory=TmuxArray)
    # Run when focus enters a client.
    client_focus_in: TmuxArray[str] = field(default_factory=TmuxArray)
    # Run when focus exits a client.
    client_focus_out: TmuxArray[str] = field(default_factory=TmuxArray)
    # Run when a client is resized.
    client_resized: TmuxArray[str] = field(default_factory=TmuxArray)
    # Run when a client's attached session is changed.
    client_session_changed: TmuxArray[str] = field(default_factory=TmuxArray)
    # Run when the program running in a pane exits, but remain-on-exit is on so the pane
    # has not closed.
    pane_died: TmuxArray[str] = field(default_factory=TmuxArray)
    # Run when the program running in a pane exits.
    pane_exited: TmuxArray[str] = field(default_factory=TmuxArray)
    # Run when the focus enters a pane, if the focus-events option is on.
    pane_focus_in: TmuxArray[str] = field(default_factory=TmuxArray)
    # Run when the focus exits a pane, if the focus-events option is on.
    pane_focus_out: TmuxArray[str] = field(default_factory=TmuxArray)
    # Run when the terminal clipboard is set using the xterm(1) escape sequence.
    pane_set_clipboard: TmuxArray[str] = field(default_factory=TmuxArray)
    # Run when a new session created.
    session_created: TmuxArray[str] = field(default_factory=TmuxArray)
    # Run when a session closed.
    session_closed: TmuxArray[str] = field(default_factory=TmuxArray)
    # Run when a session is renamed.
    session_renamed: TmuxArray[str] = field(default_factory=TmuxArray)
    # Run when a window is linked into a session.
    window_linked: TmuxArray[str] = field(default_factory=TmuxArray)
    # Run when a window is renamed.
    window_renamed: TmuxArray[str] = field(default_factory=TmuxArray)
    # Run when a window is resized. This may be after the client-resized hook is run.
    window_resized: TmuxArray[str] = field(default_factory=TmuxArray)
    # Run when a window is unlinked from a session.
    window_unlinked: TmuxArray[str] = field(default_factory=TmuxArray)

    # --- Tmux control mode hooks ---
    # The client has detached.
    client_detached_control: TmuxArray[str] = field(default_factory=TmuxArray)
    # The client is now attached to the session with ID session-id, which is named name.
    client_session_changed_control: TmuxArray[str] = field(default_factory=TmuxArray)
    # An error has happened in a configuration file.
    config_error: TmuxArray[str] = field(default_factory=TmuxArray)
    # The pane has been continued after being paused (if the pause-after flag is set,
    # see refresh-client -A).
    continue_control: TmuxArray[str] = field(default_factory=TmuxArray)
    # The tmux client is exiting immediately, either because it is not attached to any
    # session or an error occurred.
    exit_control: TmuxArray[str] = field(default_factory=TmuxArray)
    # New form of %output sent when the pause-after flag is set.
    extended_output: TmuxArray[str] = field(default_factory=TmuxArray)
    # The layout of a window with ID window-id changed.
    layout_change: TmuxArray[str] = field(default_factory=TmuxArray)
    # A message sent with the display-message command.
    message_control: TmuxArray[str] = field(default_factory=TmuxArray)
    # A window pane produced output.
    output: TmuxArray[str] = field(default_factory=TmuxArray)
    # The pane with ID pane-id has changed mode.
    pane_mode_changed: TmuxArray[str] = field(default_factory=TmuxArray)
    # Paste buffer name has been changed.
    paste_buffer_changed: TmuxArray[str] = field(default_factory=TmuxArray)
    # Paste buffer name has been deleted.
    paste_buffer_deleted: TmuxArray[str] = field(default_factory=TmuxArray)
    # The pane has been paused (if the pause-after flag is set).
    pause_control: TmuxArray[str] = field(default_factory=TmuxArray)
    # The client is now attached to the session with ID session-id, which is named name.
    session_changed_control: TmuxArray[str] = field(default_factory=TmuxArray)
    # The current session was renamed to name.
    session_renamed_control: TmuxArray[str] = field(default_factory=TmuxArray)
    # The session with ID session-id changed its active window to the window with ID
    # window-id.
    session_window_changed: TmuxArray[str] = field(default_factory=TmuxArray)
    # A session was created or destroyed.
    sessions_changed: TmuxArray[str] = field(default_factory=TmuxArray)
    # The value of the format associated with subscription name has changed to value.
    subscription_changed: TmuxArray[str] = field(default_factory=TmuxArray)
    # The window with ID window-id was created but is not linked to the current session.
    unlinked_window_add: TmuxArray[str] = field(default_factory=TmuxArray)
    # The window with ID window-id, which is not linked to the current session, was
    # closed.
    unlinked_window_close: TmuxArray[str] = field(default_factory=TmuxArray)
    # The window with ID window-id, which is not linked to the current session, was
    # renamed.
    unlinked_window_renamed: TmuxArray[str] = field(default_factory=TmuxArray)
    # The window with ID window-id was linked to the current session.
    window_add: TmuxArray[str] = field(default_factory=TmuxArray)
    # The window with ID window-id closed.
    window_close: TmuxArray[str] = field(default_factory=TmuxArray)
    # The layout of a window with ID window-id changed. The new layout is window-layout.
    # The window's visible layout is window-visible-layout and the window flags are
    # window-flags.
    window_layout_changed: TmuxArray[str] = field(default_factory=TmuxArray)
    # The active pane in the window with ID window-id changed to the pane with ID
    # pane-id.
    window_pane_changed: TmuxArray[str] = field(default_factory=TmuxArray)
    # The window with ID window-id was renamed to name.
    window_renamed_control: TmuxArray[str] = field(default_factory=TmuxArray)

    # --- After hooks - Run after specific tmux commands complete ---
    # Runs after 'bind-key' completes
    after_bind_key: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'capture-pane' completes
    after_capture_pane: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'copy-mode' completes
    after_copy_mode: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'display-message' completes
    after_display_message: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'display-panes' completes
    after_display_panes: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'kill-pane' completes
    after_kill_pane: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'list-buffers' completes
    after_list_buffers: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'list-clients' completes
    after_list_clients: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'list-keys' completes
    after_list_keys: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'list-panes' completes
    after_list_panes: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'list-sessions' completes
    after_list_sessions: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'list-windows' completes
    after_list_windows: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'load-buffer' completes
    after_load_buffer: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'lock-server' completes
    after_lock_server: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'new-session' completes
    after_new_session: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'new-window' completes
    after_new_window: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'paste-buffer' completes
    after_paste_buffer: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'pipe-pane' completes
    after_pipe_pane: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'queue' command is processed
    after_queue: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'refresh-client' completes
    after_refresh_client: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'rename-session' completes
    after_rename_session: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'rename-window' completes
    after_rename_window: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'resize-pane' completes
    after_resize_pane: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'resize-window' completes
    after_resize_window: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'save-buffer' completes
    after_save_buffer: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'select-layout' completes
    after_select_layout: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'select-pane' completes
    after_select_pane: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'select-window' completes
    after_select_window: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'send-keys' completes
    after_send_keys: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'set-buffer' completes
    after_set_buffer: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'set-environment' completes
    after_set_environment: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'set-hook' completes
    after_set_hook: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'set-option' completes
    after_set_option: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'show-environment' completes
    after_show_environment: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'show-messages' completes
    after_show_messages: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'show-options' completes
    after_show_options: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'split-window' completes
    after_split_window: TmuxArray[str] = field(default_factory=TmuxArray)
    # Runs after 'unbind-key' completes
    after_unbind_key: TmuxArray[str] = field(default_factory=TmuxArray)

    @classmethod
    def from_stdout(cls, value: t.List[str]) -> "Hooks":
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

        assert is_tmux_array_list(output_exploded)

        output_renamed: "HookArray" = {
            k.lstrip("%").replace("-", "_"): v for k, v in output_exploded.items()
        }

        return cls(**output_renamed)
