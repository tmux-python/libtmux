"""Typed reads of the numeric and flag fields on a tmux object.

tmux reports every format field as text, so the dataclass fields on
:class:`~libtmux.Pane`, :class:`~libtmux.Window`, :class:`~libtmux.Session`
and :class:`~libtmux.Client` are ``str | None``. ``obj.typed`` reads the same
fields as ``int`` and ``bool``, and leaves the text fields alone.

Examples
--------
>>> pane.typed.pane_width > 0
True
>>> pane.typed.pane_active
True
>>> pane.pane_width == str(pane.typed.pane_width)
True
"""

from __future__ import annotations

import typing as t

from libtmux import exc

if t.TYPE_CHECKING:
    from collections.abc import Callable

    from typing_extensions import Self

    from libtmux.neo import Obj

R = t.TypeVar("R")


def _parse_flag(raw: str) -> bool:
    return raw == "1"


class _Field(t.Generic[R]):
    """One typed field: parse tmux's text, or report that it is missing."""

    name: str

    def __init__(self, parse: Callable[[str], t.Any], *, required: bool) -> None:
        self._parse = parse
        self._required = required

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    @t.overload
    def __get__(self, obj: None, owner: type) -> Self: ...

    @t.overload
    def __get__(self, obj: ObjFields, owner: type) -> R: ...

    def __get__(self, obj: ObjFields | None, owner: type) -> Self | R | None:
        if obj is None:
            return self
        raw = t.cast("str | None", getattr(obj._obj, self.name))
        if raw is None:
            if self._required:
                raise exc.FieldNotReported(self.name)
            return None
        return t.cast("R", self._parse(raw))


def _int() -> _Field[int]:
    return _Field(int, required=True)


def _opt_int() -> _Field[int | None]:
    return _Field(int, required=False)


def _flag() -> _Field[bool]:
    return _Field(_parse_flag, required=True)


def _opt_flag() -> _Field[bool | None]:
    return _Field(_parse_flag, required=False)


class ObjFields:
    """Typed view of the numeric and flag fields of one object.

    Returned by ``typed`` on :class:`~libtmux.Pane`,
    :class:`~libtmux.Window` and :class:`~libtmux.Session`. It reads the
    object's current field values on every access, so it follows
    ``refresh()``, and it holds no copy.

    A field is ``int`` or ``bool`` when tmux reports it for every live object
    on every supported version; reading it from an object that was never
    listed raises :exc:`~libtmux.exc.FieldNotReported`. A field is
    ``int | None`` or ``bool | None`` when tmux leaves it empty for some live
    objects (``pane_dead_status`` on a pane that is still running) or when
    the running tmux is too old to know it.
    """

    __slots__ = ("_obj",)

    def __init__(self, obj: Obj) -> None:
        self._obj = obj

    active_window_index = _int()
    alternate_saved_x = _int()
    alternate_saved_y = _int()
    bracket_paste_flag = _opt_flag()
    cursor_flag = _flag()
    cursor_x = _int()
    cursor_y = _int()
    history_bytes = _int()
    history_limit = _int()
    history_size = _int()
    insert_flag = _flag()
    keypad_cursor_flag = _flag()
    keypad_flag = _flag()
    last_window_index = _int()
    line = _opt_int()
    mouse_all_flag = _flag()
    mouse_any_flag = _flag()
    mouse_button_flag = _flag()
    mouse_sgr_flag = _flag()
    mouse_standard_flag = _flag()
    origin_flag = _flag()
    pane_active = _flag()
    pane_at_bottom = _flag()
    pane_at_left = _flag()
    pane_at_right = _flag()
    pane_at_top = _flag()
    pane_bottom = _int()
    pane_dead = _flag()
    pane_dead_signal = _opt_int()
    pane_dead_status = _opt_int()
    pane_dead_time = _opt_int()
    pane_floating_flag = _opt_flag()
    pane_format = _flag()
    pane_height = _int()
    pane_in_mode = _int()
    pane_index = _int()
    pane_input_off = _flag()
    pane_last = _flag()
    pane_left = _int()
    pane_marked = _flag()
    pane_marked_set = _flag()
    pane_pb_progress = _opt_int()
    pane_pid = _opt_int()
    pane_pipe = _flag()
    pane_pipe_pid = _opt_int()
    pane_right = _int()
    pane_synchronized = _flag()
    pane_top = _int()
    pane_width = _int()
    pane_x = _opt_int()
    pane_y = _opt_int()
    pane_z = _opt_int()
    pane_zoomed_flag = _opt_flag()
    pid = _int()
    scroll_region_lower = _int()
    scroll_region_upper = _int()
    session_activity = _int()
    session_attached = _int()
    session_created = _int()
    session_format = _flag()
    session_group_attached = _opt_int()
    session_group_many_attached = _opt_flag()
    session_group_size = _opt_int()
    session_grouped = _flag()
    session_last_attached = _opt_int()
    session_many_attached = _flag()
    session_marked = _flag()
    session_windows = _int()
    start_time = _int()
    synchronized_output_flag = _opt_flag()
    uid = _opt_int()
    window_active = _flag()
    window_active_clients = _int()
    window_active_sessions = _int()
    window_activity = _int()
    window_activity_flag = _flag()
    window_bell_flag = _flag()
    window_bigger = _opt_flag()
    window_cell_height = _int()
    window_cell_width = _int()
    window_end_flag = _flag()
    window_format = _flag()
    window_height = _int()
    window_index = _int()
    window_last_flag = _flag()
    window_linked = _flag()
    window_linked_sessions = _int()
    window_marked_flag = _flag()
    window_offset_x = _opt_int()
    window_offset_y = _opt_int()
    window_panes = _int()
    window_silence_flag = _flag()
    window_stack_index = _int()
    window_start_flag = _flag()
    window_width = _int()
    window_zoomed_flag = _flag()
    wrap_flag = _flag()

    def __repr__(self) -> str:
        """Name the view and the object it reads."""
        return f"{type(self).__name__}({self._obj!r})"


class ClientFields(ObjFields):
    """Typed view of a :class:`~libtmux.Client`, with the ``client_*`` fields.

    Every ``client_*`` field is optional: tmux leaves them empty for a client
    without a terminal, such as a control-mode client.
    """

    __slots__ = ()

    client_activity = _opt_int()
    client_cell_height = _opt_int()
    client_cell_width = _opt_int()
    client_control_mode = _opt_flag()
    client_created = _opt_int()
    client_discarded = _opt_int()
    client_height = _opt_int()
    client_pid = _opt_int()
    client_prefix = _opt_flag()
    client_readonly = _opt_flag()
    client_uid = _opt_int()
    client_utf8 = _opt_flag()
    client_width = _opt_int()
    client_written = _opt_int()
