"""Internal constants."""

from __future__ import annotations

import io
import typing as t
from dataclasses import dataclass, field

from libtmux._internal.dataclasses import SkipDefaultFieldsReprMixin
from libtmux._internal.sparse_array import SparseArray, is_sparse_array_list

if t.TYPE_CHECKING:
    from typing import TypeAlias


T = t.TypeVar("T")

TerminalFeatures = dict[str, list[str]]
HookArray: TypeAlias = "dict[str, SparseArray[str]]"


@dataclass(repr=False)
class ServerOptions(
    SkipDefaultFieldsReprMixin,
):
    """Container for tmux server options.

    Each field carries the value of the tmux server option named the same with
    hyphens in place of underscores. A field keeps its default — ``None``, or an
    empty container for the array options — when tmux reports no value for it.

    Attributes
    ----------
    backspace : str | None
        Key tmux sends when backspace is pressed.
    buffer_limit : int | None
        Number of paste buffers kept before the oldest is discarded.
    command_alias : SparseArray[str]
        Command aliases by array index, each a ``name=value`` pair expanded when a
        command is parsed.
    default_terminal : str | None
        Value of ``TERM`` given to new windows.
    copy_command : str | None
        Shell command that copy-pipe pipes to when called without arguments.
    escape_time : int | None
        Milliseconds tmux waits after an escape to decide whether it starts a key
        sequence.
    editor : str | None
        Command tmux runs when it needs an editor.
    exit_empty : Literal["on", "off"] | None
        Whether the server exits once no sessions remain.
    exit_unattached : Literal["on", "off"] | None
        Whether the server exits once no clients are attached.
    extended_keys : Literal["on", "off", "always"] | None
        Whether keys pressed with Control, Meta, or Shift are reported as extended
        sequences, and whether the program in the pane may pick the mode.
    focus_events : Literal["on", "off"] | None
        Whether focus events are requested from the terminal and passed through to
        applications.
    history_file : str | None
        File command prompt history is loaded from and written back to; an empty
        value keeps no history file.
    message_limit : int | None
        Number of messages kept in each client's message log.
    prompt_history_limit : int | None
        Number of entries kept in the history file for each type of prompt.
    set_clipboard : Literal["on", "external", "off"] | None
        Whether tmux sets the terminal clipboard, and whether applications may
        create paste buffers with the escape sequence.
    terminal_features : TerminalFeatures
        Feature names tmux applies to each terminal type pattern, for classes of
        functionality terminfo does not report.
    terminal_overrides : SparseArray[str]
        terminfo capability overrides by array index, each a terminal type pattern
        followed by ``name=value`` entries.
    user_keys : SparseArray[str]
        Escape sequences by array index, bound to the keys named ``User0``,
        ``User1``, and so on.
    default_client_command : str | None
        Command run when tmux is invoked without one.
    extended_keys_format : Literal["csi-u", "xterm"] | None
        Escape sequence format used to report modified keys to applications.
    get_clipboard : Literal["off", "buffer", "request", "both"] | None
        How tmux answers an application that asks for the clipboard.
    """

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
    # tmux 3.7+ options
    get_clipboard: t.Literal["off", "buffer", "request", "both"] | None = field(
        default=None,
    )

    def __init__(self, **kwargs: object) -> None:
        # Convert hyphenated keys to underscored attribute names and assign values
        for key, value in kwargs.items():
            key_underscored = key.replace("-", "_")
            setattr(self, key_underscored, value)


@dataclass(repr=False)
class SessionOptions(
    SkipDefaultFieldsReprMixin,
):
    """Container for tmux session options.

    Each field carries the value of the tmux session option named the same with
    hyphens in place of underscores. A field keeps its default — ``None``, or an
    empty container for the array options — when tmux reports no value for it.

    Attributes
    ----------
    activity_action : Literal["any", "none", "current", "other"] | None
        Which windows raise an alert on activity while monitor-activity is on.
    assume_paste_time : int | None
        Milliseconds below which consecutive input counts as a paste and key
        bindings are not processed; zero disables.
    base_index : int | None
        Index of the first window in the session.
    bell_action : Literal["any", "none", "current", "other"] | None
        Which windows raise an alert on a bell while monitor-bell is on.
    default_command : str | None
        Command run in new windows; empty starts a login shell from default-shell.
    default_shell : str | None
        Full path of the shell used when default-command is empty.
    default_size : str | None
        Size of new windows as ``WIDTHxHEIGHT``, used when window-size is manual
        or a session is created detached.
    destroy_unattached : Literal["on", "off"] | None
        Whether the session is destroyed once its last client detaches.
    detach_on_destroy : Literal["off", "on", "no-detached", "previous", "next"] | None
        Where a client goes when the session it is attached to is destroyed.
    display_panes_active_colour : str | None
        Colour of the active pane indicator shown by display-panes.
    display_panes_colour : str | None
        Colour of the inactive pane indicators shown by display-panes.
    display_panes_time : int | None
        Milliseconds the display-panes indicators stay on screen.
    display_time : int | None
        Milliseconds status line messages and indicators stay on screen; zero
        holds them until a key is pressed.
    history_limit : int | None
        Lines of scrollback kept per pane, applied to panes created afterwards.
    key_table : str | None
        Key table key presses are looked up in first.
    lock_after_time : int | None
        Seconds of inactivity after which the session locks; zero never locks.
    lock_command : str | None
        Shell command run to lock each client.
    menu_style : str | None
        Style of menus.
    menu_selected_style : str | None
        Style of the selected menu item.
    menu_border_style : str | None
        Style of menu borders.
    menu_border_lines : Literal["single", ...] | None
        Characters used to draw menu borders.
    message_command_style : str | None
        Style of the command prompt while in vi command mode.
    message_line : int | None
        Status line row that messages and the command prompt are drawn on.
    message_style : str | None
        Style of messages and the command prompt.
    mouse : Literal["on", "off"] | None
        Whether tmux captures the mouse so mouse events run key bindings.
    prefix : str | None
        Key accepted as the prefix key; the tmux key name ``None`` sets no prefix.
    prefix2 : str | None
        Second key accepted as a prefix key.
    renumber_windows : Literal["on", "off"] | None
        Whether closing a window renumbers the rest so no gaps are left.
    repeat_time : int | None
        Milliseconds a key bound with ``-r`` may be repeated without the prefix.
    set_titles : Literal["on", "off"] | None
        Whether tmux sets the client terminal title.
    set_titles_string : str | None
        Format expanded to build the terminal title while set-titles is on.
    silence_action : Literal["any", "none", "current", "other"] | None
        Which windows raise an alert on silence while monitor-silence is on.
    status : Literal["off", "on"] | int | None
        Whether the status line is shown, and how many rows it occupies.
    status_format : list[str] | None
        Format of each status line row, one entry per row.
    status_interval : int | None
        Seconds between status line updates; zero disables timed redraws.
    status_justify : Literal["left", "centre", "right", "absolute-centre"] | None
        Position of the window list within the status line.
    status_keys : Literal["vi", "emacs"] | None
        Key set used at the command prompt and in the status line.
    status_left : str | None
        Format drawn on the left of the status line.
    status_left_length : int | None
        Maximum width of the left side of the status line.
    status_left_style : str | None
        Style of the left side of the status line.
    status_position : Literal["top", "bottom"] | None
        Edge of the terminal the status line sits on.
    status_right : str | None
        Format drawn on the right of the status line.
    status_right_length : int | None
        Maximum width of the right side of the status line.
    status_right_style : str | None
        Style of the right side of the status line.
    status_style : str | None
        Style of the status line.
    update_environment : SparseArray[str]
        Environment variable names by array index, copied from the client into the
        session environment when a session is created or attached.
    visual_activity : Literal["on", "off", "both"] | None
        Whether an activity alert shows a message, rings the bell, or both.
    visual_bell : Literal["on", "off", "both"] | None
        Whether a bell alert shows a message, rings the bell, or both.
    visual_silence : Literal["on", "off", "both"] | None
        Whether a silence alert shows a message, rings the bell, or both.
    word_separators : str | None
        Characters that separate words for the copy mode word commands.
    focus_follows_mouse : Literal["on", "off"] | None
        Whether moving the mouse into a pane selects it, while mouse is on.
    message_format : str | None
        Format of the prompt and message area, where ``#{message}`` expands to the
        prompt or message text.
    prompt_command_cursor_style : Literal["default", ...] | None
        Shape of the cursor in the command prompt while in vi command mode, and
        whether it blinks.
    """

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
    # tmux 3.7+ options
    focus_follows_mouse: t.Literal["on", "off"] | None = field(default=None)
    message_format: str | None = field(default=None)
    prompt_command_cursor_style: (
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

    def __init__(self, **kwargs: object) -> None:
        # Convert hyphenated keys to underscored attribute names and assign values
        for key, value in kwargs.items():
            key_underscored = key.replace("-", "_")
            setattr(self, key_underscored, value)


@dataclass(repr=False)
class WindowOptions(
    SkipDefaultFieldsReprMixin,
):
    """Container for tmux window options.

    Each field carries the value of the tmux window option named the same with
    hyphens in place of underscores, and is ``None`` when tmux reports no value
    for it.

    Attributes
    ----------
    aggressive_resize : Literal["on", "off"] | None
        Whether the window is sized from the sessions where it is the current
        window rather than from every session it is linked to.
    automatic_rename : Literal["on", "off"] | None
        Whether tmux renames the window from automatic-rename-format.
    automatic_rename_format : str | None
        Format used to build the name while automatic-rename is on.
    clock_mode_colour : str | None
        Colour of the clock in clock mode.
    clock_mode_style : Literal["12", "24"] | None
        Hour format of the clock in clock mode.
    fill_character : str | None
        Character filling terminal area the window does not cover.
    main_pane_height : int | str | None
        Height of the main pane in the main-horizontal layouts, in rows or as a
        percentage such as ``"10%"``.
    main_pane_width : int | str | None
        Width of the main pane in the main-vertical layouts, in columns or as a
        percentage such as ``"10%"``.
    copy_mode_match_style : str | None
        Style of search matches in copy mode.
    copy_mode_mark_style : str | None
        Style of the line holding the mark in copy mode.
    copy_mode_current_match_style : str | None
        Style of the search match the cursor is on in copy mode.
    mode_keys : Literal["vi", "emacs"] | None
        Key set used in copy mode.
    mode_style : str | None
        Style of indicators and highlighting in window modes.
    monitor_activity : Literal["on", "off"] | None
        Whether activity in the window raises an alert.
    monitor_bell : Literal["on", "off"] | None
        Whether a bell in the window raises an alert.
    monitor_silence : int | None
        Seconds of silence after which the window raises an alert; zero disables.
    other_pane_height : int | str | None
        Height of the panes beside the main one in the main-horizontal layouts, in
        rows or as a percentage; zero has no effect.
    other_pane_width : int | str | None
        Width of the panes beside the main one in the main-vertical layouts, in
        columns or as a percentage; zero has no effect.
    pane_active_border_style : str | None
        Style of the border around the active pane.
    pane_base_index : int | None
        Index of the first pane in the window.
    pane_border_format : str | None
        Format of the text shown in pane border status lines.
    pane_border_indicators : Literal["off", "colour", "arrows", "both"] | None
        How the active pane is marked on the border, by colouring it, by arrow
        markers, by both, or not at all.
    pane_border_lines : Literal["single", "double", "heavy", "simple", "number"] | None
        Characters used to draw pane borders.
    pane_border_status : Literal["off", "top", "bottom"] | None
        Whether pane border status lines are drawn, and on which border.
    pane_border_style : str | None
        Style of the borders around panes other than the active one.
    popup_style : str | None
        Style of popups.
    popup_border_style : str | None
        Style of popup borders.
    popup_border_lines : Literal["single", ...] | None
        Characters used to draw popup borders.
    window_status_activity_style : str | None
        Style of a window in the status line while it has an activity alert.
    window_status_bell_style : str | None
        Style of a window in the status line while it has a bell alert.
    window_status_current_format : str | None
        Format of the current window in the status line window list.
    window_status_current_style : str | None
        Style of the current window in the status line.
    window_status_format : str | None
        Format of windows other than the current one in the status line window
        list.
    window_status_last_style : str | None
        Style of the last active window in the status line.
    window_status_separator : str | None
        Text drawn between windows in the status line window list.
    window_status_style : str | None
        Style of windows other than the current and last ones in the status line.
    window_size : Literal["largest", "smallest", "manual", "latest"] | None
        How tmux derives the window size from the attached clients.
    wrap_search : Literal["on", "off"] | None
        Whether a copy mode search wraps around the end of the pane contents.
    tiled_layout_max_columns : int | None
        Maximum columns in the tiled layout, with further panes stacked in extra
        rows; zero means no limit.
    copy_mode_line_numbers : Literal["off", ...] | None
        Whether copy mode shows line numbers, and whether they are counted from
        the start of the history or from the cursor.
    copy_mode_line_number_style : str | None
        Style of line numbers in copy mode.
    copy_mode_current_line_number_style : str | None
        Style of the line number on the cursor line in copy mode.
    tree_mode_preview_format : str | None
        Format of the preview indicator in tree mode.
    tree_mode_preview_style : str | None
        Style of the preview indicator in tree mode.
    window_pane_status_format : str | None
        Format of panes other than the current one in the status line pane list.
    window_pane_current_status_format : str | None
        Format of the current pane in the status line pane list.
    """

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
    # tmux 3.7+ options
    copy_mode_line_numbers: (
        t.Literal["off", "default", "absolute", "relative", "hybrid"] | None
    ) = field(default=None)
    copy_mode_line_number_style: str | None = field(default=None)
    copy_mode_current_line_number_style: str | None = field(default=None)
    tree_mode_preview_format: str | None = field(default=None)
    tree_mode_preview_style: str | None = field(default=None)
    window_pane_status_format: str | None = field(default=None)
    window_pane_current_status_format: str | None = field(default=None)

    def __init__(self, **kwargs: object) -> None:
        # Convert hyphenated keys to underscored attribute names and assign values
        for key, value in kwargs.items():
            key_underscored = key.replace("-", "_")
            setattr(self, key_underscored, value)


@dataclass(repr=False)
class PaneOptions(
    SkipDefaultFieldsReprMixin,
):
    """Container for tmux pane options.

    Each field carries the value of the tmux pane option named the same with
    hyphens in place of underscores, and is ``None`` when tmux reports no value
    for it.

    Attributes
    ----------
    allow_passthrough : Literal["on", "off", "all"] | None
        Whether programs in the pane may bypass tmux with the passthrough escape
        sequence, and whether an invisible pane may do so.
    allow_rename : Literal["on", "off"] | None
        Whether programs in the pane may rename the window with an escape
        sequence.
    alternate_screen : Literal["on", "off"] | None
        Whether programs in the pane may use the terminal alternate screen, which
        restores the earlier pane contents when they exit.
    cursor_colour : str | None
        Colour of the cursor in the pane.
    pane_colours : list[str] | None
        Colour palette the pane uses for the colours numbered zero to 255, in
        index order.
    cursor_style : Literal["default", ...] | None
        Shape of the cursor in the pane, and whether it blinks.
    remain_on_exit : Literal["on", "off", "failed", "key"] | None
        Whether the pane stays open once the program running in it exits.
    remain_on_exit_format : str | None
        Text shown at the bottom of a pane held open by remain-on-exit.
    scroll_on_clear : Literal["on", "off"] | None
        Whether clearing the whole screen scrolls its contents into history first.
    synchronize_panes : Literal["on", "off"] | None
        Whether input is duplicated to the other panes in the window that also
        have this on.
    window_active_style : str | None
        Style of the pane while it is the active pane.
    window_style : str | None
        Style of the pane while it is not the active pane.
    pane_scrollbars : Literal["off", "modal", "on"] | None
        Whether a character based scrollbar is drawn beside the pane, all the time
        or only while the pane is in copy or view mode.
    pane_scrollbars_style : str | None
        Style of the pane scrollbar, whose width and pad attributes size it and
        the gap to the pane.
    tree_mode_preview_format : str | None
        Format of the preview indicator in tree mode.
    pane_active_border_style : str | None
        Style of the pane border while the pane is active.
    pane_border_style : str | None
        Style of the pane border while the pane is not active.
    """

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
    remain_on_exit: t.Literal["on", "off", "failed", "key"] | None = field(default=None)
    remain_on_exit_format: str | None = field(default=None)
    scroll_on_clear: t.Literal["on", "off"] | None = field(default=None)
    synchronize_panes: t.Literal["on", "off"] | None = field(default=None)
    window_active_style: str | None = field(default=None)
    window_style: str | None = field(default=None)
    # tmux 3.5+ options
    pane_scrollbars: t.Literal["off", "modal", "on"] | None = field(default=None)
    pane_scrollbars_style: str | None = field(default=None)
    # tmux 3.7+ options. Among the new options only tree-mode-preview-format is
    # window+pane scope; the copy-mode, tree-mode-preview-style, and
    # window-pane-status options are window-only, so they live on WindowOptions.
    tree_mode_preview_format: str | None = field(default=None)
    # tmux 3.7 widened pane-active-border-style / pane-border-style from window
    # to window+pane scope (set -p now works), so they are typed on panes too.
    pane_active_border_style: str | None = field(default=None)
    pane_border_style: str | None = field(default=None)

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
    A field holds an empty :class:`SparseArray` when tmux reports no commands
    for that hook.

    Attributes
    ----------
    alert_activity : SparseArray[str]
        Run when a window has activity. See monitor-activity.
    alert_bell : SparseArray[str]
        Run when a window has received a bell. See monitor-bell.
    alert_silence : SparseArray[str]
        Run when a window has been silent. See monitor-silence.
    client_active : SparseArray[str]
        Run when a client becomes the latest active client of its session.
    client_attached : SparseArray[str]
        Run when a client is attached.
    client_detached : SparseArray[str]
        Run when a client is detached.
    client_focus_in : SparseArray[str]
        Run when focus enters a client.
    client_focus_out : SparseArray[str]
        Run when focus exits a client.
    client_resized : SparseArray[str]
        Run when a client is resized.
    client_session_changed : SparseArray[str]
        Run when a client's attached session is changed.
    pane_died : SparseArray[str]
        Run when the program running in a pane exits, but remain-on-exit is on so the
        pane has not closed.
    pane_exited : SparseArray[str]
        Run when the program running in a pane exits.
    pane_focus_in : SparseArray[str]
        Run when the focus enters a pane, if the focus-events option is on.
    pane_focus_out : SparseArray[str]
        Run when the focus exits a pane, if the focus-events option is on.
    pane_set_clipboard : SparseArray[str]
        Run when the terminal clipboard is set using the xterm(1) escape sequence.
    session_created : SparseArray[str]
        Run when a new session created.
    session_closed : SparseArray[str]
        Run when a session closed.
    session_renamed : SparseArray[str]
        Run when a session is renamed.
    window_linked : SparseArray[str]
        Run when a window is linked into a session.
    window_renamed : SparseArray[str]
        Run when a window is renamed.
    window_resized : SparseArray[str]
        Run when a window is resized. This may be after the client-resized hook is run.
    window_unlinked : SparseArray[str]
        Run when a window is unlinked from a session.
    pane_title_changed : SparseArray[str]
        Run when a pane title changes (tmux 3.5+).
    client_light_theme : SparseArray[str]
        Run when terminal reports a light theme (tmux 3.5+).
    client_dark_theme : SparseArray[str]
        Run when terminal reports a dark theme (tmux 3.5+).
    client_detached_control : SparseArray[str]
        The client has detached.
    client_session_changed_control : SparseArray[str]
        The client is now attached to the session with ID session-id, which is named
        name.
    config_error : SparseArray[str]
        An error has happened in a configuration file.
    continue_control : SparseArray[str]
        The pane has been continued after being paused (if the pause-after flag is set,
        see refresh-client -A).
    exit_control : SparseArray[str]
        The tmux client is exiting immediately, either because it is not attached to any
        session or an error occurred.
    extended_output : SparseArray[str]
        New form of %output sent when the pause-after flag is set.
    layout_change : SparseArray[str]
        The layout of a window with ID window-id changed.
    message_control : SparseArray[str]
        A message sent with the display-message command.
    output : SparseArray[str]
        A window pane produced output.
    pane_mode_changed : SparseArray[str]
        The pane with ID pane-id has changed mode.
    paste_buffer_changed : SparseArray[str]
        Paste buffer name has been changed.
    paste_buffer_deleted : SparseArray[str]
        Paste buffer name has been deleted.
    pause_control : SparseArray[str]
        The pane has been paused (if the pause-after flag is set).
    session_changed_control : SparseArray[str]
        The client is now attached to the session with ID session-id, which is named
        name.
    session_renamed_control : SparseArray[str]
        The current session was renamed to name.
    session_window_changed : SparseArray[str]
        The session with ID session-id changed its active window to the window with ID
        window-id.
    sessions_changed : SparseArray[str]
        A session was created or destroyed.
    subscription_changed : SparseArray[str]
        The value of the format associated with subscription name has changed to value.
    unlinked_window_add : SparseArray[str]
        The window with ID window-id was created but is not linked to the current
        session.
    unlinked_window_close : SparseArray[str]
        The window with ID window-id, which is not linked to the current session, was
        closed.
    unlinked_window_renamed : SparseArray[str]
        The window with ID window-id, which is not linked to the current session, was
        renamed.
    window_add : SparseArray[str]
        The window with ID window-id was linked to the current session.
    window_close : SparseArray[str]
        The window with ID window-id closed.
    window_layout_changed : SparseArray[str]
        The layout of a window with ID window-id changed. The new layout is
        window-layout. The window's visible layout is window-visible-layout and the
        window flags are window-flags.
    window_pane_changed : SparseArray[str]
        The active pane in the window with ID window-id changed to the pane with ID
        pane-id.
    window_renamed_control : SparseArray[str]
        The window with ID window-id was renamed to name.
    after_bind_key : SparseArray[str]
        Runs after 'bind-key' completes.
    after_capture_pane : SparseArray[str]
        Runs after 'capture-pane' completes.
    after_copy_mode : SparseArray[str]
        Runs after 'copy-mode' completes.
    after_display_message : SparseArray[str]
        Runs after 'display-message' completes.
    after_display_panes : SparseArray[str]
        Runs after 'display-panes' completes.
    after_kill_pane : SparseArray[str]
        Runs after 'kill-pane' completes.
    after_list_buffers : SparseArray[str]
        Runs after 'list-buffers' completes.
    after_list_clients : SparseArray[str]
        Runs after 'list-clients' completes.
    after_list_keys : SparseArray[str]
        Runs after 'list-keys' completes.
    after_list_panes : SparseArray[str]
        Runs after 'list-panes' completes.
    after_list_sessions : SparseArray[str]
        Runs after 'list-sessions' completes.
    after_list_windows : SparseArray[str]
        Runs after 'list-windows' completes.
    after_load_buffer : SparseArray[str]
        Runs after 'load-buffer' completes.
    after_lock_server : SparseArray[str]
        Runs after 'lock-server' completes.
    after_new_session : SparseArray[str]
        Runs after 'new-session' completes.
    after_new_window : SparseArray[str]
        Runs after 'new-window' completes.
    after_paste_buffer : SparseArray[str]
        Runs after 'paste-buffer' completes.
    after_pipe_pane : SparseArray[str]
        Runs after 'pipe-pane' completes.
    after_queue : SparseArray[str]
        Runs after 'queue' command is processed.
    after_refresh_client : SparseArray[str]
        Runs after 'refresh-client' completes.
    after_rename_session : SparseArray[str]
        Runs after 'rename-session' completes.
    after_rename_window : SparseArray[str]
        Runs after 'rename-window' completes.
    after_resize_pane : SparseArray[str]
        Runs after 'resize-pane' completes.
    after_resize_window : SparseArray[str]
        Runs after 'resize-window' completes.
    after_save_buffer : SparseArray[str]
        Runs after 'save-buffer' completes.
    after_select_layout : SparseArray[str]
        Runs after 'select-layout' completes.
    after_select_pane : SparseArray[str]
        Runs after 'select-pane' completes.
    after_select_window : SparseArray[str]
        Runs after 'select-window' completes.
    after_send_keys : SparseArray[str]
        Runs after 'send-keys' completes.
    after_set_buffer : SparseArray[str]
        Runs after 'set-buffer' completes.
    after_set_environment : SparseArray[str]
        Runs after 'set-environment' completes.
    after_set_hook : SparseArray[str]
        Runs after 'set-hook' completes.
    after_set_option : SparseArray[str]
        Runs after 'set-option' completes.
    after_show_environment : SparseArray[str]
        Runs after 'show-environment' completes.
    after_show_messages : SparseArray[str]
        Runs after 'show-messages' completes.
    after_show_options : SparseArray[str]
        Runs after 'show-options' completes.
    after_split_window : SparseArray[str]
        Runs after 'split-window' completes.
    after_unbind_key : SparseArray[str]
        Runs after 'unbind-key' completes.
    command_error : SparseArray[str]
        Runs when a command fails (tmux 3.5+).

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
