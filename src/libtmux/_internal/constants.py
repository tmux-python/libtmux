from __future__ import annotations

import typing as t
from dataclasses import dataclass, field

from libtmux._internal.dataclasses import SkipDefaultFieldsReprMixin

TerminalFeatures = dict[str, list[str]]


T = t.TypeVar("T")


class TmuxArray(dict[int, T], t.Generic[T]):
    """Support non-sequential indexes without raising IndexError."""

    def add(self, index: int, value: T) -> None:
        self[index] = value

    def append(self, value: T) -> None:
        index = max(self.keys()) + 1
        self[index] = value

    def iter_values(self) -> t.Iterator[T]:
        for index in sorted(self.keys()):
            yield self[index]

    def as_list(self) -> list[T]:
        return [self[index] for index in sorted(self.keys())]


@dataclass(repr=False)
class ServerOptions(
    SkipDefaultFieldsReprMixin,
):
    backspace: str | None = field(default=None)
    buffer_limit: int | None = field(default=None)
    command_alias: TmuxArray[str] = field(default_factory=TmuxArray)
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
    update_environment: list[str] | None = field(default=None)
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

    def __init__(self, **kwargs: object) -> None:
        # Convert hyphenated keys to underscored attribute names and assign values
        for key, value in kwargs.items():
            key_underscored = key.replace("-", "_")
            setattr(self, key_underscored, value)


@dataclass(repr=False)
class PaneOptions(
    SkipDefaultFieldsReprMixin,
):
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
