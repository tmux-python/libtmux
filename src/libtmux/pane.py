"""Pythonization of the :ref:`tmux(1)` pane.

libtmux.pane
~~~~~~~~~~~~

"""

from __future__ import annotations

import dataclasses
import logging
import pathlib
import re
import time
import typing as t
import uuid
import warnings

from libtmux import exc
from libtmux._internal.env import pane_id_from_env
from libtmux.capture import (
    CaptureCursor,
    CaptureSince,
    TextMatch,
    _capture_since,
    _wait_for_idle,
    _wait_for_text,
)
from libtmux.common import (
    _escape_trailing_semicolon,
    get_version_str,
    has_gte_version,
    raise_if_stderr,
    tmux_cmd,
)
from libtmux.constants import (
    PANE_DIRECTION_FLAG_MAP,
    RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP,
    OptionScope,
    PaneDirection,
    ResizeAdjustmentDirection,
)
from libtmux.formats import FORMAT_SEPARATOR
from libtmux.hooks import HooksMixin
from libtmux.neo import PANE_LABEL_OPTION, Obj, fetch_obj
from libtmux.options import OptionsMixin
from libtmux.run import _run

if t.TYPE_CHECKING:
    import sys
    import types

    from libtmux._internal.types import StrPath
    from libtmux.run import PaneRunResult

    from .server import Server
    from .session import Session
    from .window import Window

    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing_extensions import Self

logger = logging.getLogger(__name__)

_DEFAULT_LABEL_OPTION = PANE_LABEL_OPTION


def _check_label_option(option: str) -> None:
    if not option.startswith("@"):
        msg = f"label option must start with '@', got {option!r}"
        raise ValueError(msg)


class PaneExit(t.NamedTuple):
    """How a pane's process ended, as returned by :meth:`Pane.wait`.

    Attributes
    ----------
    status : int or None
        Exit status. *None* when a signal ended the process.
    signal : int or None
        Terminating signal number. *None* when the process exited normally,
        and always *None* on tmux 3.2a, which does not report it.

    Examples
    --------
    >>> PaneExit(status=3, signal=None)
    PaneExit(status=3, signal=None)

    >>> status, signal = PaneExit(status=None, signal=9)
    >>> signal
    9

    .. versionadded:: 0.63
    """

    status: int | None
    signal: int | None


_WAIT_POLL_START = 0.01
_WAIT_POLL_CAP = 0.1


_HEX_TOKEN_RE = re.compile(r"(?:0[xX])?([0-9a-fA-F]{1,2}|(?:[0-9a-fA-F]{2})+)")


def _hex_key_args(text: str) -> tuple[str, ...]:
    """Split hex text into the one-byte arguments ``send-keys -H`` takes.

    Examples
    --------
    >>> _hex_key_args("1b5b32")
    ('1b', '5b', '32')
    >>> _hex_key_args("0x1b 0x5b")
    ('1b', '5b')
    >>> _hex_key_args("1b5")
    Traceback (most recent call last):
    ...
    ValueError: invalid hex bytes: '1b5'
    """
    args: list[str] = []
    for token in text.split() or [text]:
        match = _HEX_TOKEN_RE.fullmatch(token)
        if match is None:
            msg = f"invalid hex bytes: {token!r}"
            raise ValueError(msg)
        digits = match.group(1)
        args += [digits[i : i + 2] for i in range(0, len(digits), 2)]
    return tuple(args)


_LAYOUT_NAMES = frozenset(
    {
        "even-horizontal",
        "even-vertical",
        "main-horizontal",
        "main-horizontal-mirrored",
        "main-vertical",
        "main-vertical-mirrored",
        "tiled",
    },
)
_CUSTOM_LAYOUT = re.compile(r"[0-9a-f]{4},\d+x\d+,")


def _check_layout(layout: str) -> None:
    """Reject a layout tmux would not recognize, before any pane is created.

    tmux 3.3a exits the whole server on an unrecognized layout name, which
    would destroy every session on the socket.
    """
    if layout not in _LAYOUT_NAMES and not _CUSTOM_LAYOUT.match(layout):
        msg = f"unrecognized layout {layout!r}"
        raise ValueError(msg)


@dataclasses.dataclass()
class Pane(
    Obj,
    OptionsMixin,
    HooksMixin,
):
    """:term:`tmux(1)` :term:`Pane` [pane_manual]_.

    ``Pane`` instances can send commands directly to a pane, or traverse
    between linked tmux objects.

    Attributes
    ----------
    default_option_scope : OptionScope | None
        Scope :class:`~libtmux.options.OptionsMixin` falls back to when an
        option call leaves ``scope`` unset. ``OptionScope.Pane`` sends
        ``set-option`` and ``show-options`` with tmux's ``-p`` flag; ``None``
        sends no scope flag, which tmux resolves as session scope.
    default_hook_scope : OptionScope | None
        Scope :class:`~libtmux.hooks.HooksMixin` falls back to when a hook
        call leaves ``scope`` unset. ``OptionScope.Pane`` sends ``set-hook``
        and ``show-hooks`` with tmux's ``-p`` flag; ``None`` sends no scope
        flag, which tmux resolves as session scope.
    server : Server
        Server the pane was queried from, and the connection every command
        and refresh runs over.
    pane_label : str or None
        The ``@name`` user option as of the last listing, ``""`` when unset;
        ``None`` until a listing has run. Read it through :attr:`label`.

    Examples
    --------
    >>> pane
    Pane(%1 Window(@1 1:..., Session($1 ...)))

    >>> pane in window.panes
    True

    >>> pane.window
    Window(@1 1:..., Session($1 ...))

    >>> pane.session
    Session($1 ...)

    The pane can be used as a context manager to ensure proper cleanup:

    >>> with window.split() as pane:
    ...     pane.send_keys('echo "Hello"')
    ...     # Do work with the pane
    ...     # Pane will be killed automatically when exiting the context

    Notes
    -----
    .. versionchanged:: 0.8
        Renamed from ``.tmux`` to ``.cmd``.

    References
    ----------
    .. [pane_manual] tmux pane. openbsd manpage for TMUX(1).
           "Each window displayed by tmux may be split into one or more
           panes; each pane takes up a certain area of the display and is
           a separate terminal."

       https://man.openbsd.org/tmux.1#WINDOWS_AND_PANES.
       Accessed April 1st, 2018.
    """

    default_option_scope: OptionScope | None = OptionScope.Pane
    default_hook_scope: OptionScope | None = OptionScope.Pane
    server: Server
    pane_label: str | None = None

    def __enter__(self) -> Self:
        """Enter the context, returning self.

        Returns
        -------
        :class:`Pane`
            The pane instance
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Exit the context, killing the pane if it exists.

        Parameters
        ----------
        exc_type : type[BaseException] | None
            The type of the exception that was raised
        exc_value : BaseException | None
            The instance of the exception that was raised
        exc_tb : types.TracebackType | None
            The traceback of the exception that was raised
        """
        if (
            self.pane_id is not None
            and len(self.window.panes.filter(pane_id=self.pane_id)) > 0
        ):
            self.kill()

    def refresh(self) -> None:
        """Refresh pane attributes from tmux.

        Scoped to this pane's own window (``list-panes -t %ID``), so tmux --
        not libtmux -- decides which session the pane belongs to. See
        :meth:`Pane.from_pane_id`.

        Raises
        ------
        ValueError
            When ``pane_id`` is unset. Surfaces a clear error under
            ``python -O``, where an ``assert`` would be stripped.
        :exc:`~libtmux.exc.TmuxObjectDoesNotExist`
            When the pane no longer exists.
        :exc:`~libtmux.exc.LibTmuxException`
            When tmux itself is unreachable.

        Examples
        --------
        >>> pane.refresh()
        >>> pane.pane_id
        '%1'
        """
        if self.pane_id is None:
            msg = "Pane must have a pane_id to refresh"
            raise ValueError(msg)
        return super()._refresh(
            obj_key="pane_id",
            obj_id=self.pane_id,
            list_extra_args=("-t", self.pane_id),
        )

    @classmethod
    def from_pane_id(cls, server: Server, pane_id: str) -> Pane:
        """Create Pane from existing pane_id.

        tmux's ``cmd_find`` routes a ``-t`` target by *sigil*, so a ``%``-id
        handed to ``list-panes`` resolves to that pane's window and lists it.
        Every row comes back stamped with the session tmux considers canonical
        for that window -- the most recently active one -- which is the same
        session ``display-message -t %ID '#{session_id}'`` reports. A window
        linked into several sessions therefore gets one authoritative answer
        instead of "whichever session sorted last".

        Parameters
        ----------
        server : :class:`~libtmux.server.Server`
            The tmux server holding the pane.
        pane_id : str
            Pane id, e.g. ``"%3"``.

        Returns
        -------
        :class:`Pane`

        Raises
        ------
        :exc:`~libtmux.exc.TmuxObjectDoesNotExist`
            When no such pane exists on a reachable server.
        :exc:`~libtmux.exc.LibTmuxException`
            When tmux itself is unreachable.

        Examples
        --------
        >>> Pane.from_pane_id(server=pane.server, pane_id=pane.pane_id)
        Pane(%1 Window(@1 1:..., Session($1 ...)))
        """
        pane = fetch_obj(
            obj_key="pane_id",
            obj_id=pane_id,
            server=server,
            list_cmd="list-panes",
            list_extra_args=("-t", pane_id),
        )
        return cls(server=server, **pane)

    @classmethod
    def from_env(cls, env: t.Mapping[str, str] | None = None) -> Pane:
        """Return the pane this process is running inside of.

        Reads ``$TMUX`` for the server's socket and ``$TMUX_PANE`` for the pane
        id, then asks tmux for the rest. The stale session id inside ``$TMUX``
        is never consulted, so the answer stays correct after the pane's window
        has been moved or linked elsewhere.

        Parameters
        ----------
        env : :class:`typing.Mapping`, optional
            Environment to read. Defaults to :data:`os.environ`, which is what
            a process running inside a pane wants; pass an explicit mapping to
            resolve on behalf of another pane.

        Returns
        -------
        :class:`Pane`

        Raises
        ------
        :exc:`~libtmux.exc.NotInsideTmux`
            When ``$TMUX`` or ``$TMUX_PANE`` is unset or malformed.
        :exc:`~libtmux.exc.TmuxObjectDoesNotExist`
            When the pane named by ``$TMUX_PANE`` is gone.
        :exc:`~libtmux.exc.LibTmuxException`
            When the server named by ``$TMUX`` is unreachable.

        Examples
        --------
        >>> socket_path = server.cmd(  # doctest: +HIDE
        ...     "display-message", "-p", "-t", pane.pane_id, "#{socket_path}"
        ... ).stdout[0]
        >>> env = {  # doctest: +HIDE
        ...     "TMUX": f"{socket_path},1,0",
        ...     "TMUX_PANE": pane.pane_id,
        ... }

        >>> Pane.from_env(env)
        Pane(%1 Window(@1 1:..., Session($1 ...)))

        >>> Pane.from_env(env).pane_id == pane.pane_id
        True

        Outside a pane there is nothing to resolve:

        >>> from libtmux import exc
        >>> try:
        ...     Pane.from_env({})
        ... except exc.NotInsideTmux as e:
        ...     print(e)
        Not inside a tmux pane: $TMUX is unset or empty

        .. versionadded:: 0.62
        """
        from libtmux.server import Server

        return cls.from_pane_id(
            server=Server.from_env(env),
            pane_id=pane_id_from_env(env),
        )

    #
    # Relations
    #
    @property
    def window(self) -> Window:
        """Parent window of pane."""
        assert isinstance(self.window_id, str)
        from libtmux.window import Window

        return Window.from_window_id(server=self.server, window_id=self.window_id)

    @property
    def session(self) -> Session:
        """Parent session of pane."""
        return self.window.session

    """
    Commands (pane-scoped)
    """

    def cmd(
        self,
        cmd: str,
        *args: t.Any,
        target: str | int | None = None,
        timeout: float | None = None,
        input: str | bytes | None = None,  # noqa: A002
    ) -> tmux_cmd:
        """Execute tmux subcommand within pane context.

        Automatically binds target by adding  ``-t`` for object's pane ID to the
        command. Pass ``target`` to keyword arguments to override.

        Examples
        --------
        >>> pane.cmd('split-window', '-P').stdout[0]
        'libtmux...:...'

        From raw output to an enriched `Pane` object:

        >>> Pane.from_pane_id(pane_id=pane.cmd(
        ... 'split-window', '-P', '-F#{pane_id}').stdout[0], server=pane.server)
        Pane(%... Window(@... ...:..., Session($1 libtmux_...)))

        Parameters
        ----------
        target : str, optional
            Optional custom target override. By default, the target is the pane ID.
        timeout : float, optional
            Seconds to allow this command to run before the engine gives up and
            raises :exc:`~libtmux.exc.TmuxTimeout`; a subprocess engine kills
            and reaps the tmux client first. *None* (the default) waits
            indefinitely.
        input : str or bytes, optional
            Data for the tmux client's standard input, for commands that read
            ``-``. See :class:`~libtmux.common.tmux_cmd`.

        Returns
        -------
        :meth:`server.cmd`

        Raises
        ------
        :exc:`~libtmux.exc.TmuxTimeout`
            When *timeout* elapses.

        :exc:`~libtmux.exc.AsyncEngineMismatch`
            The server's engine is asynchronous; see :meth:`Server.cmd`.

        Notes
        -----
        .. versionchanged:: 0.63

           Added ``timeout``.
        """
        if target is None:
            target = self.pane_id

        return self.server.cmd(
            cmd,
            *args,
            target=target,
            timeout=timeout,
            input=input,
        )

    """
    Commands (tmux-like)
    """

    def resize(
        self,
        /,
        # Adjustments
        adjustment_direction: ResizeAdjustmentDirection | None = None,
        adjustment: int | None = None,
        # Manual
        height: str | int | None = None,
        width: str | int | None = None,
        # Zoom
        zoom: bool | None = None,
        # Mouse
        mouse: bool | None = None,
        # Optional flags
        trim_below: bool | None = None,
    ) -> Pane:
        """Resize tmux pane.

        Parameters
        ----------
        adjustment_direction : ResizeAdjustmentDirection, optional
            direction to adjust, ``Up``, ``Down``, ``Left``, ``Right``.
        adjustment : ResizeAdjustmentDirection, optional

        height : int, optional
            ``resize-pane -y`` dimensions
        width : int, optional
            ``resize-pane -x`` dimensions

        zoom : bool
            expand pane

        mouse : bool
            resize via mouse

        trim_below : bool
            trim below cursor

        Raises
        ------
        :exc:`exc.LibTmuxException`,
        :exc:`exc.PaneAdjustmentDirectionRequiresAdjustment`,
        :exc:`exc.RequiresDigitOrPercentage`

        Returns
        -------
        :class:`Pane`

        Notes
        -----
        Three types of resizing are available:

        1. Adjustments: ``adjustment_direction`` and ``adjustment``.
        2. Manual resizing: ``height`` and / or ``width``.
        3. Zoom / Unzoom: ``zoom``.
        """
        tmux_args: tuple[str, ...] = ()

        # Adjustments
        if adjustment_direction:
            if adjustment is None:
                raise exc.PaneAdjustmentDirectionRequiresAdjustment
            tmux_args += (
                f"{RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP[adjustment_direction]}",
                str(adjustment),
            )
        elif height or width:
            # Manual resizing
            if height:
                if (
                    isinstance(height, str)
                    and not height.isdigit()
                    and not height.endswith("%")
                ):
                    raise exc.RequiresDigitOrPercentage
                tmux_args += (f"-y{height}",)

            if width:
                if (
                    isinstance(width, str)
                    and not width.isdigit()
                    and not width.endswith("%")
                ):
                    raise exc.RequiresDigitOrPercentage
                tmux_args += (f"-x{width}",)
        elif zoom:
            # Zoom / Unzoom
            tmux_args += ("-Z",)
        elif mouse:
            tmux_args += ("-M",)

        if trim_below:
            tmux_args += ("-T",)

        proc = self.cmd("resize-pane", *tmux_args)

        raise_if_stderr(proc, "resize-pane")

        self.refresh()
        return self

    @t.overload
    def capture_pane(
        self,
        start: t.Literal["-"] | int | None = ...,
        end: t.Literal["-"] | int | None = ...,
        *,
        escape_sequences: bool = ...,
        escape_non_printable: bool = ...,
        join_wrapped: bool = ...,
        preserve_trailing: bool = ...,
        trim_trailing: bool = ...,
        alternate_screen: bool = ...,
        quiet: bool = ...,
        mode_screen: bool = ...,
        pending: bool = ...,
        hyperlinks: bool = ...,
        line_numbers: bool = ...,
        line_flags: bool = ...,
        to_buffer: str,
    ) -> None: ...

    @t.overload
    def capture_pane(
        self,
        start: t.Literal["-"] | int | None = ...,
        end: t.Literal["-"] | int | None = ...,
        *,
        escape_sequences: bool = ...,
        escape_non_printable: bool = ...,
        join_wrapped: bool = ...,
        preserve_trailing: bool = ...,
        trim_trailing: bool = ...,
        alternate_screen: bool = ...,
        quiet: bool = ...,
        mode_screen: bool = ...,
        pending: bool = ...,
        hyperlinks: bool = ...,
        line_numbers: bool = ...,
        line_flags: bool = ...,
        to_buffer: None = ...,
    ) -> list[str]: ...

    def capture_pane(
        self,
        start: t.Literal["-"] | int | None = None,
        end: t.Literal["-"] | int | None = None,
        *,
        escape_sequences: bool = False,
        escape_non_printable: bool = False,
        join_wrapped: bool = False,
        preserve_trailing: bool = False,
        trim_trailing: bool = False,
        alternate_screen: bool = False,
        quiet: bool = False,
        mode_screen: bool = False,
        pending: bool = False,
        hyperlinks: bool = False,
        line_numbers: bool = False,
        line_flags: bool = False,
        to_buffer: str | None = None,
    ) -> list[str] | None:
        r"""Capture text from pane.

        ``$ tmux capture-pane`` to pane.
        ``$ tmux capture-pane -S -10`` to pane.
        ``$ tmux capture-pane -E 3`` to pane.
        ``$ tmux capture-pane -S - -E -`` to pane.

        Parameters
        ----------
        start : str | int, optional
            Specify the starting line number.
            Zero is the first line of the visible pane.
            Positive numbers are lines in the visible pane.
            Negative numbers are lines in the history.
            ``-`` is the start of the history.
            Default: None
        end : str | int, optional
            Specify the ending line number.
            Zero is the first line of the visible pane.
            Positive numbers are lines in the visible pane.
            Negative numbers are lines in the history.
            ``-`` is the end of the visible pane.
            Default: None
        escape_sequences : bool, optional
            Include ANSI escape sequences for text and background attributes
            (``-e`` flag). Useful for capturing colored output.
            Default: False
        escape_non_printable : bool, optional
            Escape non-printable characters as octal ``\\xxx`` format
            (``-C`` flag). Useful for binary-safe capture.
            Default: False
        join_wrapped : bool, optional
            Join wrapped lines and preserve trailing spaces (``-J`` flag).
            Lines that were wrapped by tmux will be joined back together.
            Default: False
        preserve_trailing : bool, optional
            Preserve trailing spaces at each line's end (``-N`` flag).
            Default: False
        trim_trailing : bool, optional
            Trim trailing positions with no characters (``-T`` flag).
            Only includes characters up to the last used cell.
            Requires tmux 3.4+. If used with tmux < 3.4, a warning
            is issued and the flag is ignored.
            Default: False
        alternate_screen : bool, optional
            Capture from the alternate screen (``-a`` flag).
            Default: False

            .. versionadded:: 0.56
        quiet : bool, optional
            Suppress errors silently (``-q`` flag).
            Default: False

            .. versionadded:: 0.56
        mode_screen : bool, optional
            Capture from the mode screen (e.g. copy mode) instead of the
            pane (``-M`` flag). Requires tmux 3.6+.
            Default: False

            .. versionadded:: 0.56
        pending : bool, optional
            Capture *pending output* — the bytes tmux has read from the
            pane but not yet committed to the terminal (``-P`` flag).
            These are bytes that begin an incomplete escape sequence
            and are still pending the parser's ground state (tmux's
            ``input_pending()`` / ``since_ground`` buffer), distinct
            from the default capture (the pane's screen history).
            Useful for diagnosing programs whose output stalls
            mid-sequence.
            Default: False

            .. versionadded:: 0.57
        hyperlinks : bool, optional
            Capture only hyperlink targets in the selected lines (``-H``
            flag). Requires tmux 3.7+. If used with tmux < 3.7, a warning
            is issued and the flag is ignored.
            Default: False
        line_numbers : bool, optional
            Prefix each captured line with its line number (``-L`` flag).
            Requires tmux 3.7+. If used with tmux < 3.7, a warning is issued
            and the flag is ignored.
            Default: False
        line_flags : bool, optional
            Prefix each captured line with its flags, e.g. ``H`` for a line
            with a hyperlink (``-F`` flag). Requires tmux 3.7+. If used with
            tmux < 3.7, a warning is issued and the flag is ignored.
            Default: False
        to_buffer : str, optional
            Write the capture into the named tmux buffer (``-b`` flag)
            instead of returning it. When set, ``-p`` is omitted and
            the wrapper returns ``None``.

            .. versionadded:: 0.56

        Returns
        -------
        list[str] or None
            Captured pane content, or ``None`` when *to_buffer* is set.

        Examples
        --------
        >>> pane = window.split(shell='sh')
        >>> pane.capture_pane()
        ['$']

        >>> pane.send_keys('echo "Hello world"', enter=True)

        >>> pane.capture_pane()
        ['$ echo "Hello world"', 'Hello world', '$']

        >>> print(chr(10).join(pane.capture_pane()))
        $ echo "Hello world"
        Hello world
        $
        """
        cmd = ["capture-pane"]
        if to_buffer is not None:
            cmd.extend(["-b", to_buffer])
        else:
            cmd.append("-p")
        if start is not None:
            cmd.extend(["-S", str(start)])
        if end is not None:
            cmd.extend(["-E", str(end)])
        if escape_sequences:
            cmd.append("-e")
        if escape_non_printable:
            cmd.append("-C")
        if join_wrapped:
            cmd.append("-J")
        if preserve_trailing:
            cmd.append("-N")
        if trim_trailing:
            if has_gte_version("3.4", tmux_bin=self.server.tmux_bin):
                cmd.append("-T")
            else:
                warnings.warn(
                    "trim_trailing requires tmux 3.4+, ignoring",
                    stacklevel=2,
                )
        if alternate_screen:
            cmd.append("-a")
        if quiet:
            cmd.append("-q")
        if mode_screen:
            if has_gte_version("3.6", tmux_bin=self.server.tmux_bin):
                cmd.append("-M")
            else:
                warnings.warn(
                    "mode_screen requires tmux 3.6+, ignoring",
                    stacklevel=2,
                )
        if pending:
            cmd.append("-P")
        if hyperlinks:
            if has_gte_version("3.7", tmux_bin=self.server.tmux_bin):
                cmd.append("-H")
            else:
                warnings.warn(
                    "hyperlinks requires tmux 3.7+, ignoring",
                    stacklevel=2,
                )
        if line_numbers:
            if has_gte_version("3.7", tmux_bin=self.server.tmux_bin):
                cmd.append("-L")
            else:
                warnings.warn(
                    "line_numbers requires tmux 3.7+, ignoring",
                    stacklevel=2,
                )
        if line_flags:
            if has_gte_version("3.7", tmux_bin=self.server.tmux_bin):
                cmd.append("-F")
            else:
                warnings.warn(
                    "line_flags requires tmux 3.7+, ignoring",
                    stacklevel=2,
                )
        proc = self.cmd(*cmd)
        if to_buffer is not None:
            return None
        return proc.stdout

    def capture_since(
        self,
        cursor: CaptureCursor | None = None,
        *,
        timeout: float | None = None,
    ) -> CaptureSince:
        """Capture only the rows written since ``cursor``.

        Where :meth:`capture_pane` returns a snapshot, this returns a
        *delta* plus a fresh cursor to resume from, for watching a pane
        over time without re-reading and re-diffing the whole screen.

        The cursor is never modified: replaying the same one returns the
        same rows. Assign the returned cursor to advance.

        When tmux destroyed the anchor -- ``clear-history``, or a
        ``history-limit`` trim that discarded it --
        :attr:`~libtmux.capture.CaptureSince.lines_missed` is ``True`` and
        the rows are the current visible screen instead of a complete
        delta. Rows are never silently dropped without that flag.

        Parameters
        ----------
        cursor : CaptureCursor, optional
            Cursor from a previous call. When omitted, captures the
            current visible screen and opens a first cursor.
        timeout : float, optional
            Bound, in seconds, on each tmux call the read makes. See
            :meth:`cmd`. *None* (the default) waits as long as tmux takes.

        Returns
        -------
        CaptureSince
            ``(lines, cursor, lines_missed)``.

        Raises
        ------
        libtmux.exc.InvalidCaptureCursor
            If ``cursor`` belongs to a different pane.
        libtmux.exc.PaneLifecycleChanged
            If the pane died or was respawned since ``cursor`` was taken,
            or, when no ``cursor`` is given, if the pane is already dead.
        libtmux.exc.TmuxTimeout
            When a tmux call outlives ``timeout``.

        See Also
        --------
        libtmux.pane.Pane.capture_pane : Snapshot of the whole pane.

        Examples
        --------
        A first call opens a cursor:

        >>> first = pane.capture_since()
        >>> first.lines_missed
        False

        Nothing new has been written, so replaying it returns nothing:

        >>> pane.capture_since(first.cursor).lines
        []

        New output comes back on its own:

        >>> pane.send_keys('echo capture_since_demo', enter=True)
        >>> from libtmux.test.retry import retry_until
        >>> retry_until(
        ...     lambda: any(
        ...         'capture_since_demo' in line
        ...         for line in pane.capture_since(first.cursor).lines
        ...     ),
        ...     2,
        ... )
        True

        The cursor it was handed is untouched, so the next delta is taken
        from the cursor the call returned:

        >>> second = pane.capture_since(first.cursor)
        >>> second.cursor == first.cursor
        False

        .. versionadded:: 0.63
        """
        return _capture_since(self, cursor, timeout=timeout)

    def wait_for_text(
        self,
        pattern: str | re.Pattern[str],
        *,
        timeout: float | None = 30.0,
        since: CaptureCursor | None = None,
        regex: bool = False,
    ) -> TextMatch:
        r"""Block until ``pattern`` appears in output written after an anchor.

        Reach for this when a command you did not write, or one that runs
        in the background, prints something you need before you go on. For
        a command you send yourself, :meth:`wait` or a ``tmux wait-for``
        signal says "done" without reading the screen.

        Only rows written after the anchor are searched, so text that was
        already on screen never matches. The anchor is ``since`` when you
        pass a cursor, otherwise the pane as it is when the call starts.
        Take a cursor *before* sending a command and pass it as ``since``
        to leave no gap between sending and waiting.

        The row the cursor sat on is skipped when it held text. That row is
        a prompt, and what is added to it is the command you typed echoing
        back, which would otherwise satisfy a pattern taken from the same
        command. Rows below it are output. A pane whose prompt has not drawn
        yet has a blank cursor row, which is not skipped, so anchor after
        the shell is ready. A command long enough to wrap
        echoes onto those rows too, so for text that also appears in the
        command, build the command so the echo differs from the output
        (``printf '%s%s' PAR TIAL``) or match with a ``regex`` anchored to
        the row (``^done$``).

        The name follows ``pexpect``: this is ``expect`` for a tmux pane,
        with ``regex=False`` as its ``expect_exact`` and the returned
        ``match`` as its ``child.match``. A pattern is tried against one row
        at a time, so it cannot span lines, and a row wider than the pane
        wraps into two.

        Parameters
        ----------
        pattern : str or re.Pattern
            Text to find, literal unless ``regex`` is set. A compiled
            pattern is used as given.
        timeout : float, optional
            Seconds to wait; *None* waits for as long as it takes. Each tmux
            read inside the wait is bounded too, by what is left of the
            budget but at least one second.
        since : CaptureCursor, optional
            Search rows written after this cursor, taken from
            :meth:`capture_since`.
        regex : bool, optional
            Treat a string ``pattern`` as a regular expression.

        Returns
        -------
        TextMatch
            ``(match, cursor, lines_missed)``. ``cursor`` resumes after the
            read that found the match.

        Raises
        ------
        libtmux.exc.WaitTimeout
            When nothing matched within ``timeout``. Nothing is killed.
        libtmux.exc.TmuxTimeout
            When tmux stops answering a read for longer than the bound.
        libtmux.exc.PaneLifecycleChanged
            If the pane died or was respawned while waiting.
        libtmux.exc.InvalidCaptureCursor
            If ``since`` belongs to a different pane.

        Notes
        -----
        While the pane is on the alternate screen, a full-screen program is
        repainting the grid and nothing is matched; the wait resumes when
        the program exits.

        A flood past ``history-limit`` can destroy the anchor. The result
        then has ``lines_missed=True`` and the visible screen was searched,
        so the match may predate the wait. See :meth:`capture_since`.

        See Also
        --------
        libtmux.pane.Pane.capture_since : Read what is new without waiting.
        libtmux.pane.Pane.wait_for_idle : Wait for output to stop.

        Examples
        --------
        Take a cursor, send the command, wait for its output. The command
        is written so its echo does not contain the text it prints:

        >>> start = pane.capture_since().cursor
        >>> pane.send_keys("printf '%s%s\\n' wait_for_ text_demo", enter=True)
        >>> hit = pane.wait_for_text('wait_for_text_demo', since=start, timeout=5)
        >>> hit.match.string
        'wait_for_text_demo'
        >>> hit.lines_missed
        False

        ``regex=True`` takes a pattern, and the match carries its groups:

        >>> start = hit.cursor
        >>> pane.send_keys("printf '%s%s\\n' build_ 42_done", enter=True)
        >>> pane.wait_for_text(
        ...     r'^build_(\d+)_done$', regex=True, since=start, timeout=5
        ... ).match.group(1)
        '42'

        .. versionadded:: 0.63
        """
        return _wait_for_text(
            self,
            pattern,
            timeout=timeout,
            since=since,
            regex=regex,
        )

    def wait_for_idle(
        self,
        *,
        quiet: float = 0.25,
        timeout: float | None = 30.0,
        since: CaptureCursor | None = None,
    ) -> CaptureSince:
        """Block until the visible screen stops changing for ``quiet`` seconds.

        Reach for this when there is no text to wait for: a build that ends
        without a marker, a program that redraws and settles. A screen that
        keeps changing, a spinner included, is not idle.

        Returns what was written since ``since`` (or since the call began),
        so one call both waits and collects the output.

        Parameters
        ----------
        quiet : float, optional
            Seconds the visible screen must hold still.
        timeout : float, optional
            Seconds to wait for that to happen; *None* waits as long as it
            takes.
        since : CaptureCursor, optional
            Report rows written after this cursor.

        Returns
        -------
        CaptureSince
            ``(lines, cursor, lines_missed)``, as :meth:`capture_since`.

        Raises
        ------
        libtmux.exc.WaitTimeout
            When the screen never held still for ``quiet`` within
            ``timeout``.
        libtmux.exc.TmuxTimeout
            When tmux stops answering a read for longer than the bound.
        libtmux.exc.PaneLifecycleChanged
            If the pane died or was respawned while waiting.

        See Also
        --------
        libtmux.pane.Pane.wait_for_text : Wait for specific output.

        Examples
        --------
        >>> start = pane.capture_since().cursor
        >>> pane.send_keys('echo wait_for_idle_demo', enter=True)
        >>> settled = pane.wait_for_idle(quiet=0.1, since=start, timeout=5)
        >>> any('wait_for_idle_demo' in line for line in settled.lines)
        True

        .. versionadded:: 0.63
        """
        return _wait_for_idle(self, quiet=quiet, timeout=timeout, since=since)

    def send_keys(
        self,
        cmd: str | None = None,
        enter: bool | None = True,
        suppress_history: bool | None = False,
        literal: bool | None = False,
        reset: bool | None = None,
        copy_mode_cmd: str | None = None,
        repeat: int | None = None,
        expand_formats: bool | None = None,
        hex_keys: bool | None = None,
        target_client: str | None = None,
        key_name: bool | None = None,
    ) -> None:
        r"""``$ tmux send-keys`` to the pane.

        A leading space character is added to cmd to avoid polluting the
        user's history.

        When ``cmd`` is omitted (``None``), the wrapper emits a flag-only
        invocation — useful with ``reset=True`` or ``repeat=N`` to invoke
        tmux's deliberate ``count == 0`` branch in ``cmd-send-keys.c`` that
        runs the flag effect without sending any keys. In flag-only mode,
        ``enter`` is forced ``False`` (no keys → no Enter).

        Parameters
        ----------
        cmd : str | None, optional
            Text or input into pane. ``None`` for flag-only invocation
            (requires ``reset``, ``repeat``, or ``copy_mode_cmd`` to be set).

            .. versionchanged:: 0.57

               Now optional. ``None`` triggers tmux's flag-only path.
        enter : bool, optional
            Send enter after sending the input, default True.
        suppress_history : bool, optional
            Prepend a space to command to suppress shell history, default False.

            .. versionchanged:: 0.14

               Default changed from True to False.
        literal : bool, optional
            Send keys literally, default False.
        reset : bool, optional
            Reset terminal state before sending keys (``-R`` flag).

            .. versionadded:: 0.56
        copy_mode_cmd : str, optional
            Send a command to copy mode instead of keys (``-X`` flag).
            When set, *cmd* is ignored.

            .. versionadded:: 0.56
        repeat : int, optional
            Repeat count for the key (``-N`` flag).

            .. versionadded:: 0.56
        expand_formats : bool, optional
            Expand tmux format strings in keys (``-F`` flag).

            .. versionadded:: 0.56
        hex_keys : bool, optional
            Send keys as hex values (``-H`` flag). ``cmd`` is one or more
            bytes in hex, packed (``1b5b32``), space-separated (``1b 5b 32``),
            or ``0x``-prefixed. tmux takes one byte per argument; libtmux
            splits ``cmd`` into one argument per byte.

            .. versionadded:: 0.56
        target_client : str, optional
            Specify a target client (``-c`` flag). Requires tmux 3.4+.

            .. versionadded:: 0.56
        key_name : bool, optional
            Handle keys as key names (``-K`` flag). Requires tmux 3.4+.

            .. versionadded:: 0.56

        Raises
        ------
        ValueError
            If ``cmd`` is ``None`` and no flag-only path is selected
            (``reset``, ``repeat``, or ``copy_mode_cmd``), or ``hex_keys`` is
            set and ``cmd`` is not valid hex.
        :exc:`~libtmux.exc.LibTmuxException`
            If tmux rejects the text. tmux refuses a command above its 16 KiB
            message size (``command too long`` or ``failed to send command``);
            nothing is sent and no Enter follows. Send large text with
            :meth:`paste_text`.

        Examples
        --------
        >>> pane = window.split(shell='sh')
        >>> pane.capture_pane()
        ['$']

        >>> pane.send_keys('echo "Hello world"', enter=True)

        >>> pane.capture_pane()
        ['$ echo "Hello world"', 'Hello world', '$']

        >>> print('\n'.join(pane.capture_pane()))  # doctest: +NORMALIZE_WHITESPACE
        $ echo "Hello world"
        Hello world
        $

        Flag-only invocation — reset terminal state without sending any keys:

        >>> pane.send_keys(reset=True)
        """
        prefix = " " if suppress_history else ""

        tmux_args: tuple[str, ...] = ()

        if reset:
            tmux_args += ("-R",)

        if expand_formats:
            tmux_args += ("-F",)

        if hex_keys:
            tmux_args += ("-H",)

        if key_name:
            if has_gte_version("3.4", tmux_bin=self.server.tmux_bin):
                tmux_args += ("-K",)
            else:
                warnings.warn(
                    "key_name requires tmux 3.4+, ignoring",
                    stacklevel=2,
                )

        if literal:
            tmux_args += ("-l",)

        if repeat is not None:
            tmux_args += ("-N", str(repeat))

        if target_client is not None:
            if has_gte_version("3.4", tmux_bin=self.server.tmux_bin):
                tmux_args += ("-c", target_client)
            else:
                warnings.warn(
                    "target_client requires tmux 3.4+, ignoring",
                    stacklevel=2,
                )

        if copy_mode_cmd is not None:
            tmux_args += ("-X",)
            self.cmd("send-keys", *tmux_args, copy_mode_cmd)
        elif cmd is None:
            # Flag-only path — tmux's cmd-send-keys.c:223-225 explicitly
            # supports count == 0 when -R or -N is set, returning
            # CMD_RETURN_NORMAL without sending keys.
            if not reset and repeat is None:
                msg = (
                    "send_keys(cmd=None) requires at least one of: "
                    "reset=True, repeat=N, copy_mode_cmd=..."
                )
                raise ValueError(msg)
            self.cmd("send-keys", *tmux_args)
            return
        else:
            keys: tuple[str, ...]
            if hex_keys:
                keys = _hex_key_args(cmd)
                if prefix:
                    keys = ("20", *keys)
            else:
                keys = (_escape_trailing_semicolon(prefix + cmd),)
            proc = self.cmd("send-keys", *tmux_args, "--", *keys)
            raise_if_stderr(proc, "send-keys")

        if enter and copy_mode_cmd is None:
            self.enter()

    def run(
        self,
        command: str,
        *,
        timeout: float = 120.0,
    ) -> PaneRunResult:
        """Run a shell command in the pane; return its exit status and output.

        Reach for this instead of :meth:`send_keys` followed by
        :meth:`capture_pane` when you need to know *that the command
        finished*, *how it ended*, and *what it printed*. Nothing polls the
        screen: the shell reports back through the tmux server and
        :meth:`Server.wait_for() <libtmux.Server.wait_for>`.

        Parameters
        ----------
        command : str
            Shell command line, run by the pane's own shell (``cd`` and
            ``export`` take effect there). Multiple lines are allowed.
        timeout : float
            Seconds to wait for the command to finish. Defaults to 120.
            Every call is bounded; pass a larger number for a long command.

        Returns
        -------
        :class:`~libtmux.run.PaneRunResult`
            ``returncode``, ``stdout`` lines (stderr included), ``args``.
            A nonzero status is a result, not an exception.

        Raises
        ------
        :exc:`~libtmux.exc.PaneRunTimeout`
            When *timeout* elapses, carrying the output so far (a
            :exc:`~libtmux.exc.TmuxTimeout`). The command keeps running in
            the pane. Its ``started`` attribute is False when the pane's shell
            never acknowledged the line within five seconds: the pane is not
            at a shell prompt, or its shell cannot reach this tmux server, as
            in ``ssh`` and ``docker exec`` panes. The typed line stays in
            that pane.
        :exc:`~libtmux.exc.TmuxServerGone`
            When the tmux server exits.
        :exc:`~libtmux.exc.PaneNotFound`
            When the pane closes or dies before the command reports, such as
            a command that runs ``exit``. A pane killed from outside
            (``kill-pane``) is reported at *timeout*: tmux runs no hook for it.
        :exc:`ValueError`
            When *timeout* is not positive.

        Notes
        -----
        The pane MUST be at an interactive prompt of a Bourne-style shell
        (bash, zsh, dash and sh are tested); fish and csh are not supported.

        A syntax error or an unterminated quote in *command* is the shell's
        error and a nonzero ``returncode``. An interrupt (``C-c``) ends the
        command with status 130.

        The typed line starts with a space and, in bash, removes its own
        history entry. zsh keeps the entry unless ``hist_ignore_space`` is
        set.

        While the call waits, it installs ``pane-exited`` and ``pane-died``
        hooks (global, at an array index of their own, filtered to this pane)
        and removes them on every path out.

        Output is what the terminal drew, so cursor-addressed output arrives
        as rendered and trailing blanks are dropped.

        .. versionadded:: 0.63

        Examples
        --------
        >>> result = pane.run('echo hello')
        >>> result.returncode, result.stdout
        (0, ['hello'])

        A nonzero status is a result, not an exception:

        >>> pane.run('sh -c "echo oops; exit 3"').returncode
        3

        Bound the wait; the partial output rides on the exception:

        >>> from libtmux import exc
        >>> try:
        ...     pane.run('echo before; sleep 30', timeout=1)
        ... except exc.TmuxTimeout as e:
        ...     print(e.stdout)
        ['before']
        >>> pane.send_keys('C-c', enter=False)
        """
        return _run(self, command, timeout=timeout)

    @t.overload
    def display_message(
        self,
        cmd: str,
        get_text: t.Literal[True],
        *,
        format_string: str | None = ...,
        all_formats: bool | None = ...,
        verbose: bool | None = ...,
        no_expand: bool | None = ...,
        target_client: str | None = ...,
        delay: int | None = ...,
        notify: bool | None = ...,
        update_pane: bool | None = ...,
    ) -> list[str]: ...

    @t.overload
    def display_message(
        self,
        cmd: str,
        get_text: t.Literal[False] = ...,
        *,
        format_string: str | None = ...,
        all_formats: bool | None = ...,
        verbose: bool | None = ...,
        no_expand: bool | None = ...,
        target_client: str | None = ...,
        delay: int | None = ...,
        notify: bool | None = ...,
        update_pane: bool | None = ...,
    ) -> None: ...

    def display_message(
        self,
        cmd: str,
        get_text: bool = False,
        *,
        format_string: str | None = None,
        all_formats: bool | None = None,
        verbose: bool | None = None,
        no_expand: bool | None = None,
        target_client: str | None = None,
        delay: int | None = None,
        notify: bool | None = None,
        update_pane: bool | None = None,
    ) -> list[str] | None:
        """Display message to pane.

        Displays a message in target-client status line.
        The ``get_text=False`` path renders in the status line and is not
        programmatically verifiable; only ``get_text=True`` returns output.

        Parameters
        ----------
        cmd : str
            Special parameters to request from pane.
        get_text : bool, optional
            Returns only text without displaying a message in
            target-client status line.
        format_string : str, optional
            Format string for output (``-F`` flag).

            .. versionadded:: 0.56
        all_formats : bool, optional
            List all format variables (``-a`` flag).

            .. versionadded:: 0.56
        verbose : bool, optional
            Show format variable types (``-v`` flag).

            .. versionadded:: 0.56
        no_expand : bool, optional
            Suppress format expansion; output is returned as a literal string
            (``-l`` flag). Requires tmux 3.4+.

            .. versionadded:: 0.56
        target_client : str, optional
            Target client (``-c`` flag).

            .. versionadded:: 0.56
        delay : int, optional
            Display time in milliseconds (``-d`` flag).

            .. versionadded:: 0.56
        notify : bool, optional
            Do not wait for input (``-N`` flag).

            .. versionadded:: 0.56
        update_pane : bool, optional
            Allow the pane to keep updating while the message is displayed
            (``-C`` flag). By default tmux freezes the pane while a status
            message is shown. Requires tmux 3.6+ (introduced upstream by
            commit ``80eb460f``).

            .. versionadded:: 0.56

        Returns
        -------
        list[str] | None
            Message output if get_text is True, otherwise None.

        Notes
        -----
        Stderr from tmux is reported via :func:`warnings.warn`, not raised.
        Callers that want to escalate to an exception can wrap the call in
        :func:`warnings.catch_warnings` with ``filterwarnings("error")``.

        .. versionchanged:: 0.57
           Reports stderr via :func:`warnings.warn` instead of raising.
        """
        tmux_args: tuple[str, ...] = ()

        if get_text:
            tmux_args += ("-p",)

        if all_formats:
            tmux_args += ("-a",)

        if verbose:
            tmux_args += ("-v",)

        if no_expand:
            if has_gte_version("3.4", tmux_bin=self.server.tmux_bin):
                tmux_args += ("-l",)
            else:
                warnings.warn(
                    "no_expand requires tmux 3.4+, ignoring",
                    stacklevel=2,
                )

        if notify:
            tmux_args += ("-N",)

        if update_pane:
            if has_gte_version("3.6", tmux_bin=self.server.tmux_bin):
                tmux_args += ("-C",)
            else:
                warnings.warn(
                    "update_pane requires tmux 3.6+, ignoring",
                    stacklevel=2,
                )

        if target_client is not None:
            tmux_args += ("-c", target_client)

        if delay is not None:
            tmux_args += ("-d", str(delay))

        if format_string is not None:
            tmux_args += ("-F", format_string)

        if cmd:
            tmux_args += (cmd,)

        proc = self.cmd("display-message", *tmux_args)
        if proc.stderr:
            warnings.warn(
                f"display-message: {'; '.join(proc.stderr)}",
                stacklevel=2,
            )

        if get_text:
            return proc.stdout

        return None

    def wait(self, timeout: float | None = None) -> PaneExit:
        """Block until the pane's process exits, and return how it ended.

        Waits for the process tmux started in the pane (the shell, or the
        command given to :meth:`Window.split() <libtmux.Window.split>`), not for
        a command typed into that shell. For a typed command, have it signal
        a channel and use :meth:`Server.wait_for() <libtmux.Server.wait_for>`.

        tmux closes a pane when its process exits, taking the exit status
        with it. ``wait`` sets the pane's ``remain-on-exit`` for the duration
        of the call, so the pane stays on screen as a dead pane afterwards
        and you can kill or respawn it. The option is put back the way it
        was. A pane that is already dead is returned at once, and a pane that
        closed before ``wait`` ran is gone, so enable ``remain-on-exit``
        before the process can exit when it is short-lived.

        Parameters
        ----------
        timeout : float, optional
            Seconds to wait. *None* (the default) waits indefinitely.

        Returns
        -------
        PaneExit
            Exit ``status`` and terminating ``signal``. On tmux 3.2a
            ``signal`` is always *None*, so a process ended by a signal
            returns ``PaneExit(None, None)``.

        Raises
        ------
        :exc:`~libtmux.exc.WaitTimeout`
            When the process is still running after *timeout*.
        :exc:`~libtmux.exc.PaneNotFound`
            When the pane was closed before it could be read.
        :exc:`~libtmux.exc.TmuxServerGone`
            When the tmux server exited.

        Notes
        -----
        The wait polls the pane's state with a short, growing interval rather
        than waiting on a ``pane-died`` hook: a hook never fires for a pane that
        is killed, so a ``timeout=None`` wait would block forever, and it
        replaces any hook the pane already has.

        .. versionadded:: 0.63

        Examples
        --------
        >>> pane = window.split(attach=False, shell='sleep 0.5; exit 3')
        >>> pane.wait(timeout=30)
        PaneExit(status=3, signal=None)

        The pane remains, dead, until you remove it:

        >>> pane.refresh()
        >>> pane.pane_dead
        '1'

        >>> pane.kill()

        A process that is still running costs *timeout* seconds:

        >>> from libtmux import exc
        >>> sleeper = window.split(attach=False, shell='sleep 30')
        >>> try:
        ...     sleeper.wait(timeout=0.25)
        ... except exc.WaitTimeout:
        ...     print('still running')
        still running

        >>> sleeper.kill()
        """
        deadline = None if timeout is None else time.monotonic() + timeout

        exit_ = self._read_exit()
        if exit_ is not None:
            return exit_

        previous = self.cmd("show-options", "-pqv", "remain-on-exit").stdout
        proc = self.cmd("set-option", "-p", "remain-on-exit", "on")
        if proc.stderr:
            raise self._lost()
        try:
            interval = _WAIT_POLL_START
            while True:
                exit_ = self._read_exit()
                if exit_ is not None:
                    return exit_
                if deadline is not None and time.monotonic() >= deadline:
                    msg = f"pane {self.pane_id} still running after {timeout}s"
                    raise exc.WaitTimeout(msg)
                time.sleep(interval)
                interval = min(interval * 2, _WAIT_POLL_CAP)
        finally:
            if previous:
                self.cmd("set-option", "-p", "remain-on-exit", previous[0])
            else:
                self.cmd("set-option", "-p", "-u", "remain-on-exit")

    def _lost(self) -> exc.LibTmuxException:
        """Return the exception for a pane tmux can no longer find."""
        if not self.server.is_alive():
            return exc.TmuxServerGone(str(self.pane_id))
        return exc.PaneNotFound(self.pane_id)

    def _read_exit(self) -> PaneExit | None:
        """Return the pane's exit, or *None* while its process still runs.

        ``display-message -p`` answers success with empty fields for a pane
        that does not exist, so the pane id is part of the format and the
        answer is trusted only when it comes back.
        """
        sep = FORMAT_SEPARATOR
        fmt = sep.join(
            (
                "#{pane_id}",
                "#{pane_dead}",
                "#{pane_dead_status}",
                "#{pane_dead_signal}",
            ),
        )
        proc = self.cmd("display-message", "-p", fmt)
        row = proc.stdout[0].split(sep) if proc.stdout else []
        if proc.stderr or len(row) != 4 or row[0] != self.pane_id:
            raise self._lost()
        if row[1] != "1":
            return None
        return PaneExit(
            status=int(row[2]) if row[2] else None,
            signal=int(row[3]) if row[3] else None,
        )

    def kill(
        self,
        all_except: bool | None = None,
    ) -> None:
        """Kill :class:`Pane`.

        ``$ tmux kill-pane``.

        Examples
        --------
        Kill a pane:

        >>> pane_1 = pane.split()

        >>> pane_1 in window.panes
        True

        >>> pane_1.kill()

        >>> pane_1 not in window.panes
        True

        Kill all panes except the current one:

        >>> pane.window.resize(height=100, width=100)
        Window(@1 1...)

        >>> one_pane_to_rule_them_all = pane.split()

        >>> other_panes = pane.split(
        ...     ), pane.split()

        >>> all([p in window.panes for p in other_panes])
        True

        >>> one_pane_to_rule_them_all.kill(all_except=True)

        >>> all([p not in window.panes for p in other_panes])
        True

        >>> one_pane_to_rule_them_all in window.panes
        True
        """
        flags: tuple[str, ...] = ()

        if all_except:
            flags += ("-a",)

        proc = self.cmd(
            "kill-pane",
            *flags,
        )

        raise_if_stderr(proc, "kill-pane")

        extra: dict[str, str] = {
            "tmux_subcommand": "kill-pane",
        }
        if self.pane_id is not None:
            extra["tmux_pane"] = str(self.pane_id)
            extra["tmux_target"] = str(self.pane_id)
        msg = "other panes killed" if all_except else "pane killed"
        logger.info(msg, extra=extra)

    """
    Commands ("climber"-helpers)

    These are commands that climb to the parent scope's methods with
    additional scoped window info.
    """

    def select(
        self,
        *,
        direction: ResizeAdjustmentDirection | None = None,
        last: bool | None = None,
        keep_zoom: bool | None = None,
        mark: bool | None = None,
        clear_mark: bool | None = None,
        disable_input: bool | None = None,
        enable_input: bool | None = None,
    ) -> Pane:
        """Select pane.

        Parameters
        ----------
        direction : ResizeAdjustmentDirection, optional
            Select the pane in the given direction (``-U``, ``-D``, ``-L``,
            ``-R``).

            .. versionadded:: 0.56
        last : bool, optional
            Select the last (previously selected) pane (``-l`` flag).

            .. versionadded:: 0.56
        keep_zoom : bool, optional
            Keep the window zoomed if it was zoomed (``-Z`` flag).

            .. versionadded:: 0.56
        mark : bool, optional
            Set the marked pane (``-m`` flag).

            .. versionadded:: 0.56
        clear_mark : bool, optional
            Clear the marked pane (``-M`` flag).

            .. versionadded:: 0.56
        disable_input : bool, optional
            Disable input to the pane (``-d`` flag).

            .. versionadded:: 0.56
        enable_input : bool, optional
            Enable input to the pane (``-e`` flag).

            .. versionadded:: 0.56

        Returns
        -------
        :class:`Pane`
            Self, for method chaining.

        Examples
        --------
        >>> pane = window.active_pane
        >>> new_pane = window.split()
        >>> pane.refresh()
        >>> active_panes = [p for p in window.panes if p.pane_active == '1']

        >>> pane in active_panes
        True
        >>> new_pane in active_panes
        False

        >>> new_pane.pane_active == '1'
        False

        >>> new_pane.select()
        Pane(...)

        >>> new_pane.pane_active == '1'
        True
        """
        tmux_args: tuple[str, ...] = ()

        if direction is not None:
            tmux_args += (RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP[direction],)

        if last:
            tmux_args += ("-l",)

        if keep_zoom:
            tmux_args += ("-Z",)

        if mark:
            tmux_args += ("-m",)

        if clear_mark:
            tmux_args += ("-M",)

        if disable_input:
            tmux_args += ("-d",)

        if enable_input:
            tmux_args += ("-e",)

        proc = self.cmd("select-pane", *tmux_args)

        raise_if_stderr(proc, "select-pane")

        self.refresh()

        return self

    def select_pane(self) -> Pane:
        """Select pane.

        Notes
        -----
        .. deprecated:: 0.30

           Deprecated in favor of :meth:`.select()`.
        """
        raise exc.DeprecatedError(
            deprecated="Pane.select_pane()",
            replacement="Pane.select()",
            version="0.30.0",
        )

    def split(
        self,
        /,
        target: int | str | None = None,
        start_directory: StrPath | None = None,
        attach: bool = False,
        direction: PaneDirection | None = None,
        full_window_split: bool | None = None,
        zoom: bool | None = None,
        shell: str | None = None,
        size: str | int | None = None,
        percentage: int | None = None,
        environment: dict[str, str] | None = None,
        empty: bool | None = None,
        style: str | None = None,
        active_border_style: str | None = None,
        inactive_border_style: str | None = None,
        message: str | None = None,
        keep: bool | None = None,
        layout: str | None = None,
    ) -> Pane:
        """Split window and return :class:`Pane`, by default beneath current pane.

        Parameters
        ----------
        target : optional
            Optional, custom *target-pane*, used by :meth:`Window.split`.
        attach : bool, optional
            make new window the current window after creating it, default
            True.
        start_directory : str or PathLike, optional
            specifies the working directory in which the new window is created.
        direction : PaneDirection, optional
            split in direction. If none is specified, assume down.
        full_window_split: bool, optional
            split across full window width or height, rather than active pane.
        zoom: bool, optional
            expand pane
        shell : str, optional
            execute a command on splitting the window.  The pane will close
            when the command exits.

            NOTE: When this command exits the pane will close.  This feature
            is useful for long-running processes where the closing of the
            window upon completion is desired.
        size: int, optional
            Cell/row count to occupy with respect to current window.
        percentage: int, optional
            Percentage (0-100) of the window to occupy (``-p`` flag).
            Mutually exclusive with *size*.

            .. versionadded:: 0.56
        environment: dict, optional
            Environmental variables for new pane. Passthrough to ``-e``.
        empty : bool, optional
            Create an empty pane with no command (``-E`` flag) instead of
            spawning the default shell. Requires tmux 3.7+. If used with
            tmux < 3.7, a warning is issued and the flag is ignored.
        style : str, optional
            Style for the new pane (``-s``). Requires tmux 3.7+.
        active_border_style : str, optional
            Active-pane border style (``-S``). Requires tmux 3.7+.
        inactive_border_style : str, optional
            Inactive-pane border style (``-R``). Requires tmux 3.7+.
        message : str, optional
            Keep the pane open (until a key is pressed) after exit, showing this
            ``remain-on-exit-format`` message (``-m``). Requires tmux 3.7+.
        keep : bool, optional
            Keep the pane open until a key is pressed after exit (``-k``).
            Requires tmux 3.7+. These 3.7 flags warn and are ignored below 3.7.

        Examples
        --------
        >>> (pane.at_left, pane.at_right,
        ...  pane.at_top, pane.at_bottom)
        (True, True,
        True, True)

        >>> new_pane = pane.split()

        >>> (new_pane.at_left, new_pane.at_right,
        ...  new_pane.at_top, new_pane.at_bottom)
        (True, True,
        False, True)

        >>> right_pane = pane.split(direction=PaneDirection.Right)

        >>> (right_pane.at_left, right_pane.at_right,
        ...  right_pane.at_top, right_pane.at_bottom)
        (False, True,
        True, False)

        >>> left_pane = pane.split(direction=PaneDirection.Left)

        >>> (left_pane.at_left, left_pane.at_right,
        ...  left_pane.at_top, left_pane.at_bottom)
        (True, False,
        True, False)

        >>> top_pane = pane.split(direction=PaneDirection.Above)

        >>> (top_pane.at_left, top_pane.at_right,
        ...  top_pane.at_top, top_pane.at_bottom)
        (False, False,
        True, False)

        >>> pane = session.new_window().active_pane

        >>> top_pane = pane.split(direction=PaneDirection.Above, full_window_split=True)

        >>> (top_pane.at_left, top_pane.at_right,
        ...  top_pane.at_top, top_pane.at_bottom)
        (True, True,
        True, False)

        >>> bottom_pane = pane.split(
        ... direction=PaneDirection.Below,
        ... full_window_split=True)

        >>> (bottom_pane.at_left, bottom_pane.at_right,
        ...  bottom_pane.at_top, bottom_pane.at_bottom)
        (True, True,
        False, True)
        """
        tmux_formats = ["#{pane_id}" + FORMAT_SEPARATOR]

        tmux_args: tuple[str, ...] = ()

        if direction:
            tmux_args += tuple(PANE_DIRECTION_FLAG_MAP[direction])
        else:
            tmux_args += tuple(PANE_DIRECTION_FLAG_MAP[PaneDirection.Below])

        if size is not None and percentage is not None:
            msg = "Cannot specify both size and percentage"
            raise ValueError(msg)

        if size is not None:
            tmux_args += (f"-l{size}",)

        if percentage is not None:
            tmux_args += (f"-p{percentage}",)

        if full_window_split:
            tmux_args += ("-f",)

        if zoom:
            tmux_args += ("-Z",)

        tmux_args += ("-P", "-F{}".format("".join(tmux_formats)))  # output

        if start_directory:
            start_path = pathlib.Path(start_directory).expanduser()
            tmux_args += (f"-c{start_path}",)

        if not attach:
            tmux_args += ("-d",)

        if environment:
            for k, v in environment.items():
                tmux_args += (f"-e{k}={v}",)

        if empty:
            if has_gte_version("3.7", tmux_bin=self.server.tmux_bin):
                tmux_args += ("-E",)
            else:
                warnings.warn(
                    "empty requires tmux 3.7+, ignoring",
                    stacklevel=2,
                )

        styling = {
            "-s": style,
            "-S": active_border_style,
            "-R": inactive_border_style,
            "-m": message,
        }
        if keep or any(v is not None for v in styling.values()):
            if has_gte_version("3.7", tmux_bin=self.server.tmux_bin):
                for flag, value in styling.items():
                    if value is not None:
                        tmux_args += (flag, value)
                if keep:
                    tmux_args += ("-k",)
            else:
                warnings.warn(
                    "style/border/message/keep on split require tmux 3.7+, ignoring",
                    stacklevel=2,
                )

        if shell:
            tmux_args += (shell,)

        if layout is not None:
            _check_layout(layout)

        pane_cmd = self.cmd("split-window", *tmux_args, target=target)

        if (
            layout is not None
            and pane_cmd.stderr
            and any("no space for" in line for line in pane_cmd.stderr)
        ):
            self.window.select_layout(layout)
            pane_cmd = self.cmd("split-window", *tmux_args, target=target)

        if pane_cmd.stderr:
            if "pane too small" in pane_cmd.stderr:
                raise exc.LibTmuxException(pane_cmd.stderr)

            raise exc.LibTmuxException(
                pane_cmd.stderr,
                self.__dict__,
                self.window.panes,
            )

        pane_output = pane_cmd.stdout[0]

        pane_formatters = dict(
            zip(["pane_id"], pane_output.split(FORMAT_SEPARATOR), strict=False),
        )

        pane = self.from_pane_id(server=self.server, pane_id=pane_formatters["pane_id"])

        extra: dict[str, str] = {
            "tmux_subcommand": "split-window",
            "tmux_pane": str(pane.pane_id),
        }
        if self.session.session_name is not None:
            extra["tmux_session"] = str(self.session.session_name)
        if self.window.window_name is not None:
            extra["tmux_window"] = str(self.window.window_name)
        if target is not None:
            extra["tmux_target"] = str(target)

        logger.info("pane created", extra=extra)

        if layout is not None:
            self.window.select_layout(layout)

        return pane

    def new_pane(
        self,
        /,
        target: int | str | None = None,
        start_directory: StrPath | None = None,
        attach: bool = False,
        shell: str | None = None,
        environment: dict[str, str] | None = None,
        width: int | None = None,
        height: int | None = None,
        x: int | None = None,
        y: int | None = None,
        zoom: bool | None = None,
        empty: bool | None = None,
        style: str | None = None,
        active_border_style: str | None = None,
        inactive_border_style: str | None = None,
        message: str | None = None,
        keep: bool | None = None,
    ) -> Pane:
        """Create a floating :class:`Pane` via ``$ tmux new-pane`` (tmux 3.7+).

        Use :meth:`split` for a tiled pane. Floating panes sit above the tiled
        layout like a popup, but unlike a popup they are not modal and behave
        like normal panes. The returned pane has ``pane_floating_flag == "1"``.

        Parameters
        ----------
        target : int or str, optional
            Custom *target-pane*, used by :meth:`Window.new_pane`.
        start_directory : str or PathLike, optional
            Working directory for the new pane (``-c`` flag).
        attach : bool, optional
            Make the new pane the active pane, default False (``-d`` when
            not attaching).
        shell : str, optional
            Command to run in the pane. The pane closes when it exits.
        environment : dict, optional
            Environment variables for the new pane (``-e`` flag).
        width : int, optional
            Width of the floating pane in cells (``-x`` flag).
        height : int, optional
            Height of the floating pane in cells (``-y`` flag).
        x : int, optional
            X position of the floating pane in cells (``-X`` flag).
        y : int, optional
            Y position of the floating pane in cells (``-Y`` flag).
        zoom : bool, optional
            Zoom the pane (``-Z`` flag).
        empty : bool, optional
            Create an empty pane with no command (``-E`` flag).
        style : str, optional
            Style for the floating pane (``-s`` flag).
        active_border_style : str, optional
            Border style when the pane is active (``-S`` flag).
        inactive_border_style : str, optional
            Border style when the pane is inactive (``-R`` flag).
        message : str, optional
            Keep the pane open (until a key is pressed) after the command
            exits, showing this ``remain-on-exit-format`` message (``-m`` flag).
        keep : bool, optional
            Keep the pane open until a key is pressed after the command exits
            (``-k`` flag), using the default ``remain-on-exit-format``.
        layout : str, optional
            Layout to apply to the window after the split, as in
            :meth:`Window.select_layout`: a named layout such as
            ``"tiled"`` or a custom layout string. Every split halves a
            pane, so repeated splits of one window fail with tmux's "no
            space for new pane" after a handful of panes. With *layout*,
            a split that fails for lack of space applies the layout and
            is tried once more, and the layout is applied again after a
            successful split. Costs one extra ``select-layout`` call per
            split, two when the retry runs. A *layout* tmux would not
            recognize raises :exc:`ValueError` before any pane is created.


        Returns
        -------
        :class:`Pane`
            The newly created floating pane.

        Raises
        ------
        :exc:`libtmux.exc.LibTmuxException`
            If the tmux server is older than 3.7 (``new-pane`` is unavailable).

        Examples
        --------
        >>> from libtmux.common import has_gte_version
        >>> if has_gte_version("3.7"):
        ...     floating = pane.new_pane(width=40, height=10, shell="sleep 5")
        ...     is_floating = floating.pane_floating_flag
        ... else:
        ...     is_floating = "1"
        >>> is_floating
        '1'
        """
        if not has_gte_version("3.7", tmux_bin=self.server.tmux_bin):
            msg = "new_pane (floating panes) requires tmux 3.7+"
            raise exc.LibTmuxException(msg)

        tmux_formats = ["#{pane_id}" + FORMAT_SEPARATOR]

        tmux_args: tuple[str, ...] = ()

        if width is not None:
            tmux_args += (f"-x{width}",)
        if height is not None:
            tmux_args += (f"-y{height}",)
        if x is not None:
            tmux_args += (f"-X{x}",)
        if y is not None:
            tmux_args += (f"-Y{y}",)
        if zoom:
            tmux_args += ("-Z",)
        if style is not None:
            tmux_args += ("-s", style)
        if active_border_style is not None:
            tmux_args += ("-S", active_border_style)
        if inactive_border_style is not None:
            tmux_args += ("-R", inactive_border_style)
        if message is not None:
            tmux_args += ("-m", message)
        if keep:
            tmux_args += ("-k",)

        tmux_args += ("-P", "-F{}".format("".join(tmux_formats)))  # output

        if start_directory:
            start_path = pathlib.Path(start_directory).expanduser()
            tmux_args += (f"-c{start_path}",)

        if not attach:
            tmux_args += ("-d",)

        if environment:
            for k, v in environment.items():
                tmux_args += (f"-e{k}={v}",)

        if empty:
            tmux_args += ("-E",)

        if shell:
            tmux_args += (shell,)

        pane_cmd = self.cmd("new-pane", *tmux_args, target=target)

        raise_if_stderr(pane_cmd, "new-pane")

        pane_output = pane_cmd.stdout[0]

        pane_formatters = dict(
            zip(["pane_id"], pane_output.split(FORMAT_SEPARATOR), strict=False),
        )

        pane = self.from_pane_id(server=self.server, pane_id=pane_formatters["pane_id"])

        extra: dict[str, str] = {
            "tmux_subcommand": "new-pane",
            "tmux_pane": str(pane.pane_id),
        }
        if self.session.session_name is not None:
            extra["tmux_session"] = str(self.session.session_name)
        if self.window.window_name is not None:
            extra["tmux_window"] = str(self.window.window_name)
        if target is not None:
            extra["tmux_target"] = str(target)

        logger.info("floating pane created", extra=extra)

        return pane

    """
    Commands (helpers)
    """

    def set_width(self, width: int) -> Pane:
        """Set pane width.

        Parameters
        ----------
        width : int
            Pane width, in cells.

        Returns
        -------
        :class:`Pane`
            Self, for method chaining.
        """
        self.resize(width=width)
        return self

    def set_height(self, height: int) -> Pane:
        """Set pane height.

        Parameters
        ----------
        height : int
            Pane height, in cells.

        Returns
        -------
        :class:`Pane`
            Self, for method chaining.
        """
        self.resize(height=height)
        return self

    def set_title(self, title: str) -> Pane:
        """Set pane title via ``select-pane -T``.

        Parameters
        ----------
        title : str
            Title to set for the pane.

        Returns
        -------
        :class:`Pane`
            The pane instance, for method chaining.

        Examples
        --------
        >>> pane.set_title('my-title')
        Pane(...)

        >>> pane.pane_title
        'my-title'
        """
        proc = self.cmd("select-pane", "-T", title)
        raise_if_stderr(proc, "select-pane")
        self.refresh()
        return self

    def set_label(
        self,
        label: str | None,
        *,
        option: str = _DEFAULT_LABEL_OPTION,
    ) -> Pane:
        """Store a stable label on the pane as a user option.

        A program running in the pane can rewrite its title with an OSC 2
        escape, so :attr:`pane_title` is not a durable name. A user option
        is not touched by the terminal.

        Parameters
        ----------
        label : str or None
            Label to store, or ``None`` to remove it.
        option : str
            Name of the user option. Must start with ``@``.

        Returns
        -------
        :class:`Pane`
            The pane instance, for method chaining.

        Raises
        ------
        ValueError
            If ``option`` does not start with ``@``.

        Examples
        --------
        >>> pane.set_label('editor')
        Pane(...)

        >>> pane.label
        'editor'

        >>> pane.set_label(None).label is None
        True
        """
        _check_label_option(option)
        if label is None:
            self.unset_option(option, ignore_errors=True)
        else:
            self.set_option(option, label)
        if option == _DEFAULT_LABEL_OPTION:
            self.pane_label = label or ""
        return self

    def get_label(self, *, option: str = _DEFAULT_LABEL_OPTION) -> str | None:
        """Return the label stored by :meth:`set_label`, or ``None``.

        Always asks tmux, one call; :attr:`label` reuses the last listing.

        Parameters
        ----------
        option : str
            Name of the user option. Must start with ``@``.

        Raises
        ------
        ValueError
            If ``option`` does not start with ``@``.

        Examples
        --------
        >>> pane.get_label() is None
        True

        >>> pane.set_label('build', option='@role')
        Pane(...)

        >>> pane.get_label(option='@role')
        'build'
        """
        _check_label_option(option)
        value = self.show_option(option, ignore_errors=True)
        return None if value is None else str(value)

    def enter(self) -> Pane:
        """Send carriage return to pane.

        ``$ tmux send-keys`` send Enter to the pane.
        """
        self.cmd("send-keys", "Enter")
        return self

    def display_popup(
        self,
        command: str | None = None,
        *,
        close_on_exit: bool | None = None,
        close_on_success: bool | None = None,
        close_existing: bool | None = None,
        target_client: str | None = None,
        width: int | str | None = None,
        height: int | str | None = None,
        x: int | str | None = None,
        y: int | str | None = None,
        start_directory: StrPath | None = None,
        title: str | None = None,
        border_lines: str | None = None,
        style: str | None = None,
        border_style: str | None = None,
        environment: dict[str, str] | None = None,
        no_border: bool | None = None,
        close_on_any_key: bool | None = None,
        no_keys: bool | None = None,
    ) -> None:
        """Display a popup overlay via ``$ tmux display-popup``.

        Requires tmux 3.2+ and an attached client. Use
        :class:`~libtmux._internal.control_mode.ControlMode` in tests to provide
        a client.

        Parameters
        ----------
        command : str, optional
            Shell command to run in the popup.
        close_on_exit : bool, optional
            Close popup when command exits (``-E`` flag).
        close_on_success : bool, optional
            Close popup only on success exit code (``-EE`` flag, passing ``-E``
            twice).
        close_existing : bool, optional
            Close any existing popup on the client (``-C`` flag).
        target_client : str, optional
            Display the popup on this specific client (``-c`` flag).
            When omitted, tmux selects the client attached to this
            pane's session. With multiple clients attached, pass
            *target_client* to direct the popup at one of them.
        width : int or str, optional
            Popup width (``-w`` flag).
        height : int or str, optional
            Popup height (``-h`` flag).
        x : int or str, optional
            Popup x position (``-x`` flag).
        y : int or str, optional
            Popup y position (``-y`` flag).
        start_directory : str or PathLike, optional
            Working directory (``-d`` flag).
        title : str, optional
            Popup title (``-T`` flag). Requires tmux 3.3+.
        border_lines : str, optional
            Border line style (``-b`` flag). Requires tmux 3.3+.
        style : str, optional
            Popup style (``-s`` flag). Requires tmux 3.3+.
        border_style : str, optional
            Border style (``-S`` flag). Requires tmux 3.3+.
        environment : dict, optional
            Environment variables (``-e`` flag). Requires tmux 3.3+.
        no_border : bool, optional
            Open the popup without a border (``-B`` flag). If
            *border_lines* is also set, tmux ignores it. Requires tmux 3.3+.
        close_on_any_key : bool, optional
            Dismiss the popup on any key press once the inner
            command has exited (``-k`` flag). Requires tmux 3.6+.
        no_keys : bool, optional
            Do not auto-close the popup on any close-trigger keys
            (``-N`` flag). Requires tmux 3.6+.

        Examples
        --------
        Not directly testable — popup rendering requires a TTY-backed client.
        Control-mode provides an attached client for invocation but the popup
        itself is not visible or verifiable.

        >>> with control_mode() as ctl:
        ...     pane.display_popup(command='true', close_on_exit=True)
        """
        if close_on_exit and close_on_success:
            msg = (
                "close_on_exit and close_on_success are mutually exclusive: "
                "use close_on_exit=True for -E (close on any exit) "
                "or close_on_success=True for -EE (close on zero exit code only)"
            )
            raise ValueError(msg)

        tmux_args: tuple[str, ...] = ()

        if close_existing:
            tmux_args += ("-C",)

        if target_client is not None:
            tmux_args += ("-c", target_client)

        if close_on_exit:
            tmux_args += ("-E",)

        if close_on_success:
            tmux_args += ("-E", "-E")

        if width is not None:
            tmux_args += ("-w", str(width))

        if height is not None:
            tmux_args += ("-h", str(height))

        if x is not None:
            tmux_args += ("-x", str(x))

        if y is not None:
            tmux_args += ("-y", str(y))

        if start_directory is not None:
            start_path = pathlib.Path(start_directory).expanduser()
            tmux_args += ("-d", str(start_path))

        if title is not None:
            if has_gte_version("3.3", tmux_bin=self.server.tmux_bin):
                tmux_args += ("-T", title)
            else:
                warnings.warn(
                    "title requires tmux 3.3+, ignoring",
                    stacklevel=2,
                )

        if border_lines is not None:
            if has_gte_version("3.3", tmux_bin=self.server.tmux_bin):
                tmux_args += ("-b", border_lines)
            else:
                warnings.warn(
                    "border_lines requires tmux 3.3+, ignoring",
                    stacklevel=2,
                )

        if style is not None:
            if has_gte_version("3.3", tmux_bin=self.server.tmux_bin):
                tmux_args += ("-s", style)
            else:
                warnings.warn(
                    "style requires tmux 3.3+, ignoring",
                    stacklevel=2,
                )

        if border_style is not None:
            if has_gte_version("3.3", tmux_bin=self.server.tmux_bin):
                tmux_args += ("-S", border_style)
            else:
                warnings.warn(
                    "border_style requires tmux 3.3+, ignoring",
                    stacklevel=2,
                )

        if environment:
            if has_gte_version("3.3", tmux_bin=self.server.tmux_bin):
                for k, v in environment.items():
                    tmux_args += (f"-e{k}={v}",)
            else:
                warnings.warn(
                    "environment requires tmux 3.3+, ignoring",
                    stacklevel=2,
                )

        if no_border:
            if has_gte_version("3.3", tmux_bin=self.server.tmux_bin):
                tmux_args += ("-B",)
            else:
                warnings.warn(
                    "no_border requires tmux 3.3+, ignoring",
                    stacklevel=2,
                )

        if close_on_any_key:
            if has_gte_version("3.6", tmux_bin=self.server.tmux_bin):
                tmux_args += ("-k",)
            else:
                warnings.warn(
                    "close_on_any_key requires tmux 3.6+, ignoring",
                    stacklevel=2,
                )

        if no_keys:
            if has_gte_version("3.6", tmux_bin=self.server.tmux_bin):
                tmux_args += ("-N",)
            else:
                warnings.warn(
                    "no_keys requires tmux 3.6+, ignoring",
                    stacklevel=2,
                )

        if command is not None:
            tmux_args += (command,)

        proc = self.cmd("display-popup", *tmux_args)

        raise_if_stderr(proc, "display-popup")

    def paste_buffer(
        self,
        *,
        buffer_name: str | None = None,
        delete_after: bool | None = None,
        linefeed_separator: bool | None = None,
        bracket: bool | None = None,
        separator: str | None = None,
        no_vis: bool | None = None,
    ) -> None:
        """Paste a buffer into the pane via ``$ tmux paste-buffer``.

        Parameters
        ----------
        buffer_name : str, optional
            Name of the buffer to paste (``-b`` flag).
        delete_after : bool, optional
            Delete the buffer after pasting (``-d`` flag).
        linefeed_separator : bool, optional
            Use newline as the line separator instead of carriage return
            (``-r`` flag).
        bracket : bool, optional
            Use bracketed paste mode (``-p`` flag).
        separator : str, optional
            Separator between lines (``-s`` flag).
        no_vis : bool, optional
            Paste the buffer's raw bytes without passing them through
            ``vis(3)`` escaping (``-S`` flag). tmux 3.7 escapes pasted
            content by default; set this to restore the raw behaviour.
            Requires tmux 3.7+. If used with tmux < 3.7, a warning is issued
            and the flag is ignored.

        Examples
        --------
        >>> server.set_buffer('pasted_text')
        >>> pane.paste_buffer()
        """
        tmux_args: tuple[str, ...] = ()

        if delete_after:
            tmux_args += ("-d",)

        if linefeed_separator:
            tmux_args += ("-r",)

        if bracket:
            tmux_args += ("-p",)

        if buffer_name is not None:
            tmux_args += ("-b", buffer_name)

        if separator is not None:
            tmux_args += ("-s", separator)

        if no_vis:
            if has_gte_version("3.7", tmux_bin=self.server.tmux_bin):
                tmux_args += ("-S",)
            else:
                warnings.warn(
                    "no_vis requires tmux 3.7+, ignoring",
                    stacklevel=2,
                )

        proc = self.cmd("paste-buffer", *tmux_args)

        raise_if_stderr(proc, "paste-buffer")

    def paste_text(self, text: str, *, bracket: bool = True) -> None:
        r"""Paste text of any size into the pane via a throwaway paste buffer.

        Unlike :meth:`send_keys`, ``text`` is not subject to tmux's command
        size limit (16 KiB) and is never read as key names or flags. Line
        feeds stay line feeds, and control characters such as ESC arrive as
        bytes. No Enter is sent.

        The text travels on the standard input of ``$ tmux load-buffer``, so
        it reaches a uniquely named buffer without a temporary file; ``$ tmux
        paste-buffer -d -r`` then pastes and deletes it. The buffer is deleted
        when the paste fails too. An empty ``text`` sends nothing.

        Parameters
        ----------
        text : str
            Text to paste, encoded as UTF-8.
        bracket : bool, optional
            Wrap the paste in bracketed-paste markers (``-p`` flag), default
            True. tmux adds them only when the program in the pane asked for
            bracketed paste.

        Raises
        ------
        :exc:`libtmux.exc.LibTmuxException`
            If tmux refuses to load or paste the buffer.

        Examples
        --------
        >>> pane = window.split(shell='cat')
        >>> pane.paste_text('- first line\nsecond line;\n')
        >>> from libtmux.test.retry import retry_until
        >>> retry_until(lambda: '- first line' in pane.capture_pane(), raises=True)
        True
        """
        if not text:
            return

        buffer_name = f"libtmux_paste_{uuid.uuid4().hex}"
        proc = self.server.cmd("load-buffer", "-b", buffer_name, "-", input=text)
        raise_if_stderr(proc, "load-buffer")

        try:
            self.paste_buffer(
                buffer_name=buffer_name,
                delete_after=True,
                linefeed_separator=True,
                bracket=bracket,
                no_vis=has_gte_version("3.7", tmux_bin=self.server.tmux_bin) or None,
            )
        except exc.LibTmuxException:
            self.server.delete_buffer(buffer_name=buffer_name)
            raise

    def pipe(
        self,
        command: str | None = None,
        *,
        output_only: bool | None = None,
        input_only: bool | None = None,
        toggle: bool | None = None,
    ) -> None:
        """Pipe pane output to a shell command via ``$ tmux pipe-pane``.

        Parameters
        ----------
        command : str, optional
            Shell command to pipe to. If None, stops piping.
        output_only : bool, optional
            Only pipe output from the pane (``-O`` flag).
        input_only : bool, optional
            Only pipe input to the pane (``-I`` flag).
        toggle : bool, optional
            Toggle piping on/off (``-o`` flag).

        Examples
        --------
        >>> pane.pipe('cat >> /tmp/output.txt')

        Stop piping:

        >>> pane.pipe()
        """
        tmux_args: tuple[str, ...] = ()

        if output_only:
            tmux_args += ("-O",)

        if input_only:
            tmux_args += ("-I",)

        if toggle:
            tmux_args += ("-o",)

        if command is not None:
            tmux_args += (command,)

        proc = self.cmd("pipe-pane", *tmux_args)

        raise_if_stderr(proc, "pipe-pane")

    def copy_mode(
        self,
        *,
        scroll_up: bool | None = None,
        exit_on_bottom: bool | None = None,
        mouse_drag: bool | None = None,
        cancel: bool | None = None,
        page_down: bool | None = None,
        source_pane: str | None = None,
    ) -> None:
        """Enter copy mode via ``$ tmux copy-mode``.

        Parameters
        ----------
        scroll_up : bool, optional
            Start scrolled up one page (``-u`` flag).
        exit_on_bottom : bool, optional
            Exit copy mode when scrolling reaches the bottom of the
            history (``-e`` flag).
        mouse_drag : bool, optional
            Start mouse drag (``-M`` flag).
        cancel : bool, optional
            Cancel copy mode and any other modes (``-q`` flag).
        page_down : bool, optional
            Scroll a page down if already in copy mode (``-d`` flag).
            Requires tmux 3.5+.
        source_pane : str, optional
            Source pane whose contents should be displayed in copy
            mode (``-s`` flag). Lets you scroll/copy from another
            pane's history. Requires tmux 3.2+.

        Examples
        --------
        >>> pane.copy_mode()
        """
        tmux_args: tuple[str, ...] = ()

        if scroll_up:
            tmux_args += ("-u",)

        if exit_on_bottom:
            tmux_args += ("-e",)

        if mouse_drag:
            tmux_args += ("-M",)

        if page_down:
            if has_gte_version("3.5", tmux_bin=self.server.tmux_bin):
                tmux_args += ("-d",)
            else:
                warnings.warn(
                    "page_down requires tmux 3.5+, ignoring",
                    stacklevel=2,
                )

        if source_pane is not None:
            tmux_args += ("-s", source_pane)

        if cancel:
            tmux_args += ("-q",)

        proc = self.cmd("copy-mode", *tmux_args)

        raise_if_stderr(proc, "copy-mode")

    def clock_mode(self) -> None:
        """Enter clock mode via ``$ tmux clock-mode``.

        >>> pane.clock_mode()
        """
        proc = self.cmd("clock-mode")

        raise_if_stderr(proc, "clock-mode")

    def display_panes(
        self,
        *,
        duration: int | None = None,
        no_select: bool | None = None,
    ) -> None:
        """Show pane numbers via ``$ tmux display-panes``.

        Requires an attached client.

        Parameters
        ----------
        duration : int, optional
            Duration in milliseconds to display pane numbers (``-d`` flag).
        no_select : bool, optional
            Do not select a pane on keypress (``-N`` flag).

        Examples
        --------
        >>> with control_mode() as ctl:
        ...     window.active_pane.display_panes()
        """
        tmux_args: tuple[str, ...] = ()

        if duration is not None:
            tmux_args += ("-d", str(duration))

        if no_select:
            tmux_args += ("-N",)

        proc = self.server.cmd("display-panes", *tmux_args)

        raise_if_stderr(proc, "display-panes")

    def choose_buffer(self) -> None:
        """Enter buffer chooser via ``$ tmux choose-buffer``.

        >>> pane.choose_buffer()
        """
        proc = self.cmd("choose-buffer")

        raise_if_stderr(proc, "choose-buffer")

    def choose_client(self) -> None:
        """Enter client chooser via ``$ tmux choose-client``.

        >>> pane.choose_client()
        """
        proc = self.cmd("choose-client")

        raise_if_stderr(proc, "choose-client")

    def choose_tree(
        self,
        *,
        sessions_collapsed: bool | None = None,
        windows_collapsed: bool | None = None,
        format_string: str | None = None,
        filter_expression: str | None = None,
        sort_order: t.Literal["index", "name", "time", "size"] | None = None,
        reverse: bool | None = None,
        zoom: bool | None = None,
    ) -> None:
        """Enter tree chooser via ``$ tmux choose-tree``.

        Parameters
        ----------
        sessions_collapsed : bool, optional
            Start with sessions collapsed (``-s`` flag).
        windows_collapsed : bool, optional
            Start with windows collapsed (``-w`` flag).
        format_string : str, optional
            Format for each item shown in the chooser (``-F`` flag).
        filter_expression : str, optional
            Filter expression evaluated per item; only items whose
            filter expands non-zero are shown (``-f`` flag).
        sort_order : str, optional
            Sort field (``-O`` flag).
        reverse : bool, optional
            Reverse the sort order (``-r`` flag).
        zoom : bool, optional
            Zoom the pane while the chooser is active (``-Z`` flag).

        Examples
        --------
        >>> pane.choose_tree()
        """
        tmux_args: tuple[str, ...] = ()

        if sessions_collapsed:
            tmux_args += ("-s",)

        if windows_collapsed:
            tmux_args += ("-w",)

        if zoom:
            tmux_args += ("-Z",)

        if reverse:
            tmux_args += ("-r",)

        if format_string is not None:
            tmux_args += ("-F", format_string)

        if filter_expression is not None:
            tmux_args += ("-f", filter_expression)

        if sort_order is not None:
            tmux_args += ("-O", sort_order)

        proc = self.cmd("choose-tree", *tmux_args)

        raise_if_stderr(proc, "choose-tree")

    def customize_mode(self) -> None:
        """Enter customize mode via ``$ tmux customize-mode``.

        >>> pane.customize_mode()
        """
        proc = self.cmd("customize-mode")

        raise_if_stderr(proc, "customize-mode")

    def find_window(
        self,
        match_string: str,
        *,
        match_content: bool | None = None,
        case_insensitive: bool | None = None,
        match_name: bool | None = None,
        regex: bool | None = None,
        match_title: bool | None = None,
    ) -> None:
        """Search for a window matching a string via ``$ tmux find-window``.

        Opens a choose-tree filtered to matching windows.

        Parameters
        ----------
        match_string : str
            String to search for in window names, titles, and content.
        match_content : bool, optional
            Match visible pane content (``-C`` flag).
        case_insensitive : bool, optional
            Case-insensitive matching (``-i`` flag).
        match_name : bool, optional
            Match window name only (``-N`` flag).
        regex : bool, optional
            Treat match string as a regex (``-r`` flag).
        match_title : bool, optional
            Match pane title (``-T`` flag).

        Examples
        --------
        >>> pane.find_window('sh')
        """
        tmux_args: tuple[str, ...] = ()

        if match_content:
            tmux_args += ("-C",)

        if case_insensitive:
            tmux_args += ("-i",)

        if match_name:
            tmux_args += ("-N",)

        if regex:
            tmux_args += ("-r",)

        if match_title:
            tmux_args += ("-T",)

        tmux_args += (match_string,)

        proc = self.cmd("find-window", *tmux_args)

        raise_if_stderr(proc, "find-window")

    def send_prefix(self, *, secondary: bool | None = None) -> None:
        """Send the prefix key to the pane via ``$ tmux send-prefix``.

        Parameters
        ----------
        secondary : bool, optional
            Send the secondary prefix key (``-2`` flag).

        Examples
        --------
        >>> pane.send_prefix()
        """
        tmux_args: tuple[str, ...] = ()

        if secondary:
            tmux_args += ("-2",)

        proc = self.cmd("send-prefix", *tmux_args)

        raise_if_stderr(proc, "send-prefix")

    def respawn(
        self,
        *,
        shell: str | None = None,
        start_directory: StrPath | None = None,
        environment: dict[str, str] | None = None,
        kill: bool | None = None,
    ) -> None:
        """Respawn the pane process via ``$ tmux respawn-pane``.

        Parameters
        ----------
        shell : str, optional
            Shell command to run in the respawned pane.
        start_directory : str or PathLike, optional
            Working directory for the respawned pane (``-c`` flag).
        environment : dict, optional
            Environment variables (``-e`` flag).
        kill : bool, optional
            Kill the current process before respawning (``-k`` flag).
            Required if the pane is still active.

        Examples
        --------
        >>> pane = window.split(shell='sleep 1m')
        >>> pane.respawn(kill=True, shell='sh')
        """
        tmux_args: tuple[str, ...] = ()

        if kill:
            tmux_args += ("-k",)

        if start_directory is not None:
            start_path = pathlib.Path(start_directory).expanduser()
            tmux_args += (f"-c{start_path}",)

        if environment:
            for k, v in environment.items():
                tmux_args += (f"-e{k}={v}",)

        if shell:
            tmux_args += (shell,)

        proc = self.cmd("respawn-pane", *tmux_args)

        raise_if_stderr(proc, "respawn-pane")

    def move(
        self,
        target: str | Pane | Window,
        *,
        vertical: bool = True,
        detach: bool = True,
        full_window: bool | None = None,
        size: str | int | None = None,
        before: bool | None = None,
    ) -> None:
        """Move this pane to another window via ``$ tmux move-pane``.

        Similar to :meth:`join` but invokes the ``move-pane`` command directly.

        Parameters
        ----------
        target : str, Pane, or Window
            Target pane or window to move into.
        vertical : bool, optional
            Split vertically (``-v`` flag), default True. False for
            horizontal (``-h``).
        detach : bool, optional
            Do not switch to the target window (``-d`` flag), default True.
        full_window : bool, optional
            Use the full window width/height (``-f`` flag).
        size : str or int, optional
            Size for the moved pane (``-l`` flag).
        before : bool, optional
            Place the pane before the target (``-b`` flag).

        Examples
        --------
        >>> pane_to_move = window.split(shell='sleep 1m')
        >>> w2 = session.new_window(window_name='move_target')
        >>> pane_to_move.move(w2)
        """
        tmux_args: tuple[str, ...] = ()

        if vertical:
            tmux_args += ("-v",)
        else:
            tmux_args += ("-h",)

        if detach:
            tmux_args += ("-d",)

        if full_window:
            tmux_args += ("-f",)

        if size is not None:
            tmux_args += (f"-l{size}",)

        if before:
            tmux_args += ("-b",)

        from libtmux.window import Window

        if isinstance(target, Pane):
            target_id = str(target.pane_id)
        elif isinstance(target, Window):
            target_id = str(target.window_id)
        else:
            target_id = target

        tmux_args += ("-s", str(self.pane_id), "-t", target_id)

        # Use server.cmd to avoid auto-adding -t from self.cmd
        proc = self.server.cmd("move-pane", *tmux_args)

        raise_if_stderr(proc, "move-pane")

    def join(
        self,
        target: str | Pane | Window,
        *,
        vertical: bool = True,
        detach: bool = True,
        full_window: bool | None = None,
        size: str | int | None = None,
        before: bool | None = None,
    ) -> None:
        """Join this pane into another window/pane via ``$ tmux join-pane``.

        This is the inverse of :meth:`break_pane`.

        Parameters
        ----------
        target : str, Pane, or Window
            Target pane or window to join into.
        vertical : bool, optional
            Join vertically (``-v`` flag), default True. Set to False for
            horizontal (``-h``).
        detach : bool, optional
            Do not switch to the target window (``-d`` flag), default True.
        full_window : bool, optional
            Join spanning the full window width/height (``-f`` flag).
        size : str or int, optional
            Size for the joined pane (``-l`` flag).
        before : bool, optional
            Place the pane before the target (``-b`` flag).

        Examples
        --------
        >>> pane_to_join = window.split(shell='sleep 1m')
        >>> new_window = pane_to_join.break_pane()
        >>> pane_to_join.join(window)
        """
        tmux_args: tuple[str, ...] = ()

        if vertical:
            tmux_args += ("-v",)
        else:
            tmux_args += ("-h",)

        if detach:
            tmux_args += ("-d",)

        if full_window:
            tmux_args += ("-f",)

        if size is not None:
            tmux_args += (f"-l{size}",)

        if before:
            tmux_args += ("-b",)

        from libtmux.window import Window

        if isinstance(target, Pane):
            target_id = str(target.pane_id)
        elif isinstance(target, Window):
            target_id = str(target.window_id)
        else:
            target_id = target

        tmux_args += ("-s", str(self.pane_id), "-t", target_id)

        # Use server.cmd to avoid auto-adding -t from self.cmd
        proc = self.server.cmd("join-pane", *tmux_args)

        raise_if_stderr(proc, "join-pane")

    def break_pane(
        self,
        *,
        detach: bool = True,
        window_name: str | None = None,
    ) -> Window:
        """Break this pane out into a new window via ``$ tmux break-pane``.

        Parameters
        ----------
        detach : bool, optional
            Do not switch to the new window (``-d`` flag), default True.
        window_name : str, optional
            Name for the new window (``-n`` flag).

        Returns
        -------
        :class:`Window`
            The newly created window containing the pane.

        Examples
        --------
        >>> pane_to_break = window.split(shell='sleep 1m')
        >>> new_window = pane_to_break.break_pane(window_name='broken')
        >>> new_window.window_name
        'broken'
        """
        # tmux 3.7 segfaults break-pane when -n is absent and ignores -n when
        # given (NULL-deref); 3.7a reverted it. When needed, pass a placeholder
        # -n then set the real name via rename-window below. Compare the raw
        # version string to gate the workaround on the literal 3.7 release only.
        breaks_without_name = get_version_str(tmux_bin=self.server.tmux_bin) == "3.7"

        tmux_args: tuple[str, ...] = ("-P", "-F#{window_id}")

        if detach:
            tmux_args += ("-d",)

        if window_name is not None:
            tmux_args += ("-n", window_name)
        elif breaks_without_name:
            tmux_args += ("-n", "libtmux")

        tmux_args += ("-s", str(self.pane_id))

        # Use server.cmd to avoid auto-adding -t from self.cmd
        proc = self.server.cmd("break-pane", *tmux_args)

        raise_if_stderr(proc, "break-pane")

        window_id = proc.stdout[0].strip()

        from libtmux.window import Window

        window = Window.from_window_id(server=self.server, window_id=window_id)

        if window_name is not None and breaks_without_name:
            window.rename_window(window_name)

        return window

    def swap(
        self,
        target: str | Pane | None = None,
        *,
        detach: bool | None = None,
        move_up: bool | None = None,
        move_down: bool | None = None,
        keep_zoom: bool | None = None,
    ) -> None:
        """Swap this pane with another via ``$ tmux swap-pane``.

        Parameters
        ----------
        target : str or Pane, optional
            Target pane to swap with. Can be a pane ID string or Pane object.
            Mutually exclusive with *move_up* / *move_down*.

            .. versionchanged:: 0.56
               Now optional; required only when *move_up* / *move_down* are
               not set.
        detach : bool, optional
            Do not change the active pane (``-d`` flag).
        move_up : bool, optional
            Swap with the pane above (``-U`` flag). Mutually exclusive with
            *target* and *move_down*.
        move_down : bool, optional
            Swap with the pane below (``-D`` flag). Mutually exclusive with
            *target* and *move_up*.
        keep_zoom : bool, optional
            Keep the window zoomed if it was zoomed (``-Z`` flag).

        Examples
        --------
        >>> pane1 = window.active_pane
        >>> pane2 = window.split()
        >>> pane1_id, pane2_id = pane1.pane_id, pane2.pane_id
        >>> pane1.swap(pane2)
        >>> pane1.refresh()
        >>> pane2.refresh()
        """
        if move_up and move_down:
            msg = "move_up and move_down are mutually exclusive"
            raise exc.LibTmuxException(msg)

        if target is not None and (move_up or move_down):
            msg = "target is mutually exclusive with move_up/move_down"
            raise exc.LibTmuxException(msg)

        if target is None and not move_up and not move_down:
            msg = "swap requires target or move_up=True or move_down=True"
            raise exc.LibTmuxException(msg)

        tmux_args: tuple[str, ...] = ()

        if detach:
            tmux_args += ("-d",)

        if move_up:
            tmux_args += ("-U",)

        if move_down:
            tmux_args += ("-D",)

        if keep_zoom:
            tmux_args += ("-Z",)

        if target is not None:
            target_id = target.pane_id if isinstance(target, Pane) else target
            tmux_args += ("-s", str(target_id))

        proc = self.cmd("swap-pane", *tmux_args)

        raise_if_stderr(proc, "swap-pane")

    def clear_history(self, *, reset_hyperlinks: bool | None = None) -> None:
        """Clear pane history buffer via ``$ tmux clear-history``.

        Parameters
        ----------
        reset_hyperlinks : bool, optional
            Also reset hyperlinks (``-H`` flag). Requires tmux 3.4+.

            .. versionadded:: 0.56

        Examples
        --------
        >>> pane.clear_history()
        """
        tmux_args: tuple[str, ...] = ()

        if reset_hyperlinks:
            if has_gte_version("3.4", tmux_bin=self.server.tmux_bin):
                tmux_args += ("-H",)
            else:
                warnings.warn(
                    "reset_hyperlinks requires tmux 3.4+, ignoring",
                    stacklevel=2,
                )

        proc = self.cmd("clear-history", *tmux_args)

        raise_if_stderr(proc, "clear-history")

    def clear(self) -> Pane:
        """Clear pane."""
        self.send_keys("reset")
        return self

    def reset(self) -> Pane:
        r"""Reset terminal state and clear pane history.

        Sends ``send-keys -R`` and ``clear-history`` to the pane in one
        targeted tmux command sequence so output cannot land in the
        freshly-cleared grid between the terminal-state reset and the
        history clear.

        Examples
        --------
        >>> pane.reset()
        Pane(%... Window(@... ...:..., Session($1 libtmux_...)))
        """
        self.server.cmd(
            "send-keys",
            "-t",
            self.pane_id,
            "-R",
            ";",
            "clear-history",
            "-t",
            self.pane_id,
        )
        return self

    #
    # Dunder
    #
    def __eq__(self, other: object) -> bool:
        """Equal operator for :class:`Pane` object."""
        if isinstance(other, Pane):
            return self.pane_id == other.pane_id
        return False

    def __repr__(self) -> str:
        """Representation of :class:`Pane` object."""
        return f"{self.__class__.__name__}({self.pane_id} {self.window})"

    #
    # Aliases
    #
    @property
    def id(self) -> str | None:
        """Alias of :attr:`Pane.pane_id`.

        >>> pane.id
        '%1'

        >>> pane.id == pane.pane_id
        True
        """
        return self.pane_id

    @property
    def index(self) -> str | None:
        """Alias of :attr:`Pane.pane_index`.

        >>> pane.index
        '0'

        >>> pane.index == pane.pane_index
        True
        """
        return self.pane_index

    @property
    def height(self) -> str | None:
        """Alias of :attr:`Pane.pane_height`.

        >>> pane.height.isdigit()
        True

        >>> pane.height == pane.pane_height
        True
        """
        return self.pane_height

    @property
    def width(self) -> str | None:
        """Alias of :attr:`Pane.pane_width`.

        >>> pane.width.isdigit()
        True

        >>> pane.width == pane.pane_width
        True
        """
        return self.pane_width

    @property
    def title(self) -> str | None:
        """Alias for :attr:`pane_title`.

        >>> pane.set_title('test-alias')
        Pane(...)

        >>> pane.title == pane.pane_title
        True
        """
        return self.pane_title

    @property
    def label(self) -> str | None:
        """Stable pane label from the ``@name`` user option, or ``None``.

        Read from the listing that built this pane, so every pane returned by
        ``panes`` carries its label at no extra tmux call, and
        ``panes.get(label=...)`` costs the one listing. Like the other
        fields it is a snapshot: call :meth:`refresh` after another client
        changes it. A pane built without a listing reads it live.

        >>> pane.set_label('logs')
        Pane(...)

        >>> pane.label
        'logs'

        >>> window.panes.get(label='logs') == pane
        True
        """
        if self.pane_label is not None:
            return self.pane_label or None
        return self.get_label()

    @property
    def at_top(self) -> bool:
        """Typed, converted wrapper around :attr:`Pane.pane_at_top`.

        >>> pane.pane_at_top
        '1'

        >>> pane.at_top
        True
        """
        return self.pane_at_top == "1"

    @property
    def at_bottom(self) -> bool:
        """Typed, converted wrapper around :attr:`Pane.pane_at_bottom`.

        >>> pane.pane_at_bottom
        '1'

        >>> pane.at_bottom
        True
        """
        return self.pane_at_bottom == "1"

    @property
    def at_left(self) -> bool:
        """Typed, converted wrapper around :attr:`Pane.pane_at_left`.

        >>> pane.pane_at_left
        '1'

        >>> pane.at_left
        True
        """
        return self.pane_at_left == "1"

    @property
    def at_right(self) -> bool:
        """Typed, converted wrapper around :attr:`Pane.pane_at_right`.

        >>> pane.pane_at_right
        '1'

        >>> pane.at_right
        True
        """
        return self.pane_at_right == "1"

    #
    # Legacy: Redundant stuff we want to remove
    #
    def split_window(
        self,
        target: int | str | None = None,
        attach: bool = False,
        start_directory: StrPath | None = None,
        vertical: bool = True,
        shell: str | None = None,
        size: str | int | None = None,
        percent: int | None = None,  # deprecated
        environment: dict[str, str] | None = None,
    ) -> Pane:  # New Pane, not self
        """Split window at pane and return newly created :class:`Pane`.

        Parameters
        ----------
        attach : bool, optional
            Attach / select pane after creation.
        start_directory : str or PathLike, optional
            specifies the working directory in which the new pane is created.
        vertical : bool, optional
            split vertically
        percent: int, optional
            percentage to occupy with respect to current pane
        environment: dict, optional
            Environmental variables for new pane. Passthrough to ``-e``.

        Notes
        -----
        .. deprecated:: 0.33

           Deprecated in favor of :meth:`.split`.
        """
        raise exc.DeprecatedError(
            deprecated="Pane.split_window()",
            replacement="Pane.split()",
            version="0.33.0",
        )

    def get(self, key: str, default: t.Any | None = None) -> t.Any:
        """Return key-based lookup. Deprecated by attributes.

        .. deprecated:: 0.17

           Deprecated by attribute lookup, e.g. ``pane['window_name']`` is now
           accessed via ``pane.window_name``.

        """
        raise exc.DeprecatedError(
            deprecated="Pane.get()",
            replacement="direct attribute access (e.g., pane.pane_id)",
            version="0.17.0",
        )

    def __getitem__(self, key: str) -> t.Any:
        """Return item lookup by key. Deprecated in favor of attributes.

        .. deprecated:: 0.17

           Deprecated in favor of attributes. e.g. ``pane['window_name']`` is now
           accessed via ``pane.window_name``.

        """
        raise exc.DeprecatedError(
            deprecated="Pane[key] lookup",
            replacement="direct attribute access (e.g., pane.pane_id)",
            version="0.17.0",
        )

    def resize_pane(
        self,
        # Adjustments
        adjustment_direction: ResizeAdjustmentDirection | None = None,
        adjustment: int | None = None,
        # Manual
        height: str | int | None = None,
        width: str | int | None = None,
        # Zoom
        zoom: bool | None = None,
        # Mouse
        mouse: bool | None = None,
        # Optional flags
        trim_below: bool | None = None,
    ) -> Pane:
        """Resize pane, deprecated by :meth:`Pane.resize`.

        .. deprecated:: 0.28

           Deprecated by :meth:`Pane.resize`.
        """
        raise exc.DeprecatedError(
            deprecated="Pane.resize_pane()",
            replacement="Pane.resize()",
            version="0.28.0",
        )
