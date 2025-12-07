"""Pythonization of the :ref:`tmux(1)` pane.

libtmux.pane
~~~~~~~~~~~~

"""

from __future__ import annotations

import dataclasses
import logging
import pathlib
import typing as t

from libtmux import exc
from libtmux.common import tmux_cmd
from libtmux.constants import (
    PANE_DIRECTION_FLAG_MAP,
    RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP,
    OptionScope,
    PaneDirection,
    ResizeAdjustmentDirection,
)
from libtmux.formats import FORMAT_SEPARATOR
from libtmux.hooks import HooksMixin
from libtmux.neo import Obj, fetch_obj
from libtmux.options import OptionsMixin

if t.TYPE_CHECKING:
    import sys
    import types

    from libtmux._internal.types import StrPath

    from .server import Server
    from .session import Session
    from .window import Window

    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing_extensions import Self

logger = logging.getLogger(__name__)


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
    window : :class:`Window`

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
        """Refresh pane attributes from tmux."""
        assert isinstance(self.pane_id, str)
        return super()._refresh(
            obj_key="pane_id",
            obj_id=self.pane_id,
            list_extra_args=("-a",),
        )

    @classmethod
    def from_pane_id(cls, server: Server, pane_id: str) -> Pane:
        """Create Pane from existing pane_id."""
        pane = fetch_obj(
            obj_key="pane_id",
            obj_id=pane_id,
            server=server,
            list_cmd="list-panes",
            list_extra_args=("-a",),
        )
        return cls(server=server, **pane)

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

        Returns
        -------
        :meth:`server.cmd`
        """
        if target is None:
            target = self.pane_id

        return self.server.cmd(cmd, *args, target=target)

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

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        self.refresh()
        return self

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
    ) -> list[str]:
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

        Returns
        -------
        list[str]
            Captured pane content.

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
        import warnings

        from libtmux.common import has_gte_version

        cmd = ["capture-pane", "-p"]
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
            if has_gte_version("3.4"):
                cmd.append("-T")
            else:
                warnings.warn(
                    "trim_trailing requires tmux 3.4+, ignoring",
                    stacklevel=2,
                )
        return self.cmd(*cmd).stdout

    def send_keys(
        self,
        cmd: str,
        enter: bool | None = True,
        suppress_history: bool | None = False,
        literal: bool | None = False,
    ) -> None:
        r"""``$ tmux send-keys`` to the pane.

        A leading space character is added to cmd to avoid polluting the
        user's history.

        Parameters
        ----------
        cmd : str
            Text or input into pane
        enter : bool, optional
            Send enter after sending the input, default True.
        suppress_history : bool, optional
            Prepend a space to command to suppress shell history, default False.

            .. versionchanged:: 0.14

               Default changed from True to False.
        literal : bool, optional
            Send keys literally, default False.

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
        """
        prefix = " " if suppress_history else ""

        if literal:
            self.cmd("send-keys", "-l", prefix + cmd)
        else:
            self.cmd("send-keys", prefix + cmd)

        if enter:
            self.enter()

    @t.overload
    def display_message(
        self,
        cmd: str,
        get_text: t.Literal[True],
    ) -> list[str]: ...

    @t.overload
    def display_message(self, cmd: str, get_text: t.Literal[False]) -> None: ...

    def display_message(
        self,
        cmd: str,
        get_text: bool = False,
    ) -> list[str] | None:
        """Display message to pane.

        Displays a message in target-client status line.

        Parameters
        ----------
        cmd : str
            Special parameters to request from pane.
        get_text : bool, optional
            Returns only text without displaying a message in
            target-client status line.

        Returns
        -------
        list[str] | None
            Message output if get_text is True, otherwise None.
        """
        if get_text:
            return self.cmd("display-message", "-p", cmd).stdout

        self.cmd("display-message", cmd)
        return None

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

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    """
    Commands ("climber"-helpers)

    These are commands that climb to the parent scope's methods with
    additional scoped window info.
    """

    def select(self) -> Pane:
        """Select pane.

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
        proc = self.cmd("select-pane")

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

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
        environment: dict[str, str] | None = None,
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
            Cell/row or percentage to occupy with respect to current window.
        environment: dict, optional
            Environmental variables for new pane. Passthrough to ``-e``.

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

        if size is not None:
            tmux_args += (f"-l{size}",)

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

        if shell:
            tmux_args += (shell,)

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

        return self.from_pane_id(server=self.server, pane_id=pane_formatters["pane_id"])

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

    def enter(self) -> Pane:
        """Send carriage return to pane.

        ``$ tmux send-keys`` send Enter to the pane.
        """
        self.cmd("send-keys", "Enter")
        return self

    def clear(self) -> Pane:
        """Clear pane."""
        self.send_keys("reset")
        return self

    def reset(self) -> Pane:
        """Reset and clear pane history."""
        self.cmd("send-keys", r"-R \; clear-history")
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
