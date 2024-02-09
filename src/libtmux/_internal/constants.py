import typing as t
from dataclasses import dataclass, field

from libtmux._internal.dataclasses import SkipDefaultFieldsReprMixin

TerminalFeatures = t.Dict[str, t.List[str]]


T = t.TypeVar("T")


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
    update_environment: t.Optional[t.List[str]] = field(default=None)
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
