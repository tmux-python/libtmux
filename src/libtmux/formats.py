"""tmux formats: the :class:`Format` opt-in and format variables.

libtmux.formats
~~~~~~~~~~~~~~~

:class:`Format` marks a value for tmux to expand as a format; a plain ``str``
passed to libtmux is stored as typed.

:data:`FORMAT_SEPARATOR` is used at runtime by ``neo``, ``pane``, and
``session``.  The ``*_FORMATS`` lists (``SESSION_FORMATS``,
``WINDOW_FORMATS``, ``PANE_FORMATS``, etc.) are **reference documentation
only** — they are not imported or consumed at runtime. Runtime listings use
:func:`libtmux.neo.get_output_format` to build tmux format strings for the
active tmux version.

For reference: https://github.com/tmux/tmux/blob/master/format.c

"""

from __future__ import annotations

import dataclasses
import os
import typing as t

#: Characters tmux reads as format syntax, each written as tmux's character-code
#: format so it expands back to itself: ``#`` starts an expression, ``%`` is a
#: strftime field in arguments tmux also expands as a time format, and ``,``
#: and ``}`` end an argument inside ``#{...}``.
_FORMAT_ESCAPES = {ord(char): f"#{{a:{ord(char)}}}" for char in "#%,}"}


def _escape_format(text: str) -> str:
    """Return *text* written so that tmux expands it back to exactly *text*.

    ``#{a:35}`` is tmux's character-code format for ``#``. Doubling (``##``)
    is not enough: tmux keeps a run of ``#`` before ``[`` as a style, so
    ``a#[b`` would be stored as ``a##[b``.

    Examples
    --------
    >>> _escape_format("build#2")
    'build#{a:35}2'
    >>> _escape_format("a#[b")
    'a#{a:35}[b'
    >>> _escape_format("50% a,b}")
    '50#{a:37} a#{a:44}b#{a:125}'
    >>> _escape_format("plain")
    'plain'
    """
    return text.translate(_FORMAT_ESCAPES)


def _unfinished(template: str) -> str | None:
    """Return why plain text appended to *template* would not stay literal.

    Text is literal only outside tmux's expression syntax. It is not after a
    lone trailing ``#``, which combines with the next character, or inside an
    unclosed ``#{...}`` or ``#(...)``.

    Examples
    --------
    >>> _unfinished("#{session_name}-") is None
    True
    >>> _unfinished("#{session_name}#")
    'it ends with a lone #'
    >>> _unfinished("#{?pane_active,")
    'it ends inside #{...}'
    >>> _unfinished("#(echo ")
    'it ends inside #(...)'
    """
    closers: list[str] = []
    i = 0
    while i < len(template):
        char = template[i]
        if char == "#":
            if i + 1 == len(template):
                return "it ends with a lone #"
            following = template[i + 1]
            if following == "{":
                closers.append("}")
            elif following == "(":
                closers.append(")")
            i += 2
            continue
        if closers and char == closers[-1]:
            closers.pop()
        i += 1
    if closers:
        return (
            "it ends inside #{...}" if closers[-1] == "}" else "it ends inside #(...)"
        )
    return None


@dataclasses.dataclass(frozen=True, slots=True)
class Format:
    """A tmux format that tmux expands, instead of storing it as typed.

    Names, titles, start directories and file paths passed to libtmux as plain
    ``str`` are kept as typed. Wrap a format your program wrote in
    :class:`Format` to have tmux expand it, as it does for ``#{...}`` in
    ``tmux.conf``. Where tmux always expands an argument, such as
    :meth:`~libtmux.Pane.display_message`, a :class:`Format` is accepted too,
    so text from users or files can be combined with it safely.

    Only pass text your program wrote. Add text from users or files with ``+``
    or :meth:`join`, which keep it literal; place it inside an expression,
    such as a conditional or comparison, with :meth:`escape`.

    Parameters
    ----------
    template : str
        The format, in tmux's own syntax, for example
        ``"#{pane_current_path}"``.

    Examples
    --------
    Open a pane in the directory of the session's active pane:

    >>> pane.split(start_directory=Format("#{pane_current_path}"))
    Pane(...)

    Name a window after its session, with user text kept literal:

    >>> user_text = "x#S"
    >>> window.rename_window(Format("#{session_name}-") + user_text)
    Window(...)
    >>> window.window_name == f"{session.session_name}-x#S"
    True

    A plain ``str`` is never expanded:

    >>> window.rename_window("#{session_name}")
    Window(...)
    >>> window.window_name
    '#{session_name}'

    Plain text cannot be added where tmux would read it as format syntax:

    >>> Format("#{?pane_active,") + "yes"
    Traceback (most recent call last):
    ...
    ValueError: cannot add plain text to Format('#{?pane_active,'): ...
    """

    template: str

    @classmethod
    def escape(cls, text: str | Format) -> Format:
        """Return a format that tmux expands back to *text*.

        The result is safe anywhere in a format, including inside a
        conditional or comparison. A :class:`Format` is returned unchanged.

        Examples
        --------
        >>> Format.escape("x#S")
        Format('x#{a:35}S')
        >>> Format.escape(Format("#S"))
        Format('#S')

        Compare a window name with user text:

        >>> user_text = "a,b"
        >>> Format("#{==:#{window_name},") + Format.escape(user_text) + Format("}")
        Format('#{==:#{window_name},a#{a:44}b}')
        """
        if isinstance(text, Format):
            return text
        return cls(_escape_format(text))

    def join(self, parts: t.Iterable[str | Format]) -> Format:
        """Join *parts* with this format between them, escaping each ``str``.

        Examples
        --------
        >>> Format("#{session_name}:").join(["a#1", Format("#{window_index}")])
        Format('a#{a:35}1#{session_name}:#{window_index}')
        """
        joined = Format("")
        for index, part in enumerate(parts):
            if index:
                joined += self
            joined += part
        return joined

    def __add__(self, other: str | Format) -> Format:
        """Append *other*; a ``str`` is escaped and stays literal.

        Raises
        ------
        ValueError
            *other* is a ``str`` and this format ends where tmux would read
            it as format syntax.
        """
        if isinstance(other, Format):
            return Format(self.template + other.template)
        if not isinstance(other, str):
            return NotImplemented
        reason = _unfinished(self.template)
        if reason is not None:
            msg = (
                f"cannot add plain text to {self!r}: {reason}; "
                "use Format.escape() to place text inside an expression"
            )
            raise ValueError(msg)
        return Format(self.template + _escape_format(other))

    def __radd__(self, other: str) -> Format:
        """Prepend *other*; a ``str`` is escaped and stays literal."""
        if not isinstance(other, str):
            return NotImplemented
        return Format(_escape_format(other) + self.template)

    def __bool__(self) -> bool:
        """Return whether the format is non-empty, as for ``str``.

        Examples
        --------
        >>> bool(Format(""))
        False
        """
        return bool(self.template)

    def __str__(self) -> str:
        """Return the format as tmux receives it."""
        return self.template

    def __repr__(self) -> str:
        """Show the format as it would be written."""
        return f"Format({self.template!r})"


FORMAT_SEPARATOR = os.environ.get("LIBTMUX_TMUX_FORMAT_SEPARATOR", "␞")

SESSION_FORMATS = [
    "session_name",
    "session_windows",
    "session_width",
    "session_height",
    "session_id",
    "session_created",
    "session_created_string",
    "session_attached",
    # "session_grouped",  Apparently unused in tmux.
    "session_group",
]

CLIENT_FORMATS = [
    "client_cwd",
    "client_height",
    "client_width",
    "client_tty",
    "client_termname",
    "client_created",
    "client_created_string",
    "client_activity",
    "client_activity_string",
    "client_prefix",
    "client_utf8",
    "client_readonly",
    "client_session",
    "client_last_session",
]

WINDOW_FORMATS = [
    # format_window()
    "window_id",
    "window_name",
    "window_width",
    "window_height",
    "window_layout",
    "window_panes",
    # format_winlink()
    "window_index",
    "window_flags",
    "window_active",
    "window_bell_flag",
    "window_activity_flag",
    "window_silence_flag",
]

PANE_FORMATS = [
    "history_size",
    "history_limit",
    "history_bytes",
    "pane_index",
    "pane_width",
    "pane_height",
    "pane_title",
    "pane_id",
    "pane_active",
    "pane_dead",
    "pane_in_mode",
    "pane_synchronized",
    "pane_tty",
    "pane_pid",
    "pane_start_command",
    "pane_start_path",
    "pane_current_path",
    "pane_current_command",
    "cursor_x",
    "cursor_y",
    "scroll_region_upper",
    "scroll_region_lower",
    "saved_cursor_x",
    "saved_cursor_y",
    "alternate_on",
    "alternate_saved_x",
    "alternate_saved_y",
    "cursor_flag",
    "insert_flag",
    "keypad_cursor_flag",
    "keypad_flag",
    "wrap_flag",
    "mouse_standard_flag",
    "mouse_button_flag",
    "mouse_any_flag",
    "mouse_utf8_flag",
    # tmux 3.7
    "pane_flags",
    "pane_floating_flag",
    "pane_x",
    "pane_y",
    "pane_z",
    "pane_zoomed_flag",
    "pane_pb_progress",
    "pane_pb_state",
    "pane_pipe_pid",
    "bracket_paste_flag",
    "synchronized_output_flag",
]
