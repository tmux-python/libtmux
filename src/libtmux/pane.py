"""Provide a Pythonic representation of the :ref:`tmux(1)` pane.

The :class:`Pane` class models a single tmux pane, allowing commands to be
sent directly to it, as well as traversal to related :class:`Window` and
:class:`Session` objects. It offers convenience methods for splitting, resizing,
and interacting with the pane's contents.

libtmux.pane
~~~~~~~~~~~~
"""

from __future__ import annotations

import dataclasses
import logging
import pathlib
import typing as t
import warnings

from libtmux.common import has_gte_version, has_lt_version, tmux_cmd
from libtmux.constants import (
    PANE_DIRECTION_FLAG_MAP,
    RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP,
    PaneDirection,
    ResizeAdjustmentDirection,
)
from libtmux.formats import FORMAT_SEPARATOR
from libtmux.neo import Obj, fetch_obj

from . import exc

if t.TYPE_CHECKING:
    import sys
    import types

    from .server import Server
    from .session import Session
    from .window import Window

    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing_extensions import Self

logger = logging.getLogger(__name__)


@dataclasses.dataclass()
class Pane(Obj):
    """:term:`tmux(1)` :term:`Pane` [pane_manual]_.

    ``Pane`` instances can send commands directly to a pane, or traverse
    between linked tmux objects.

    Attributes
    ----------
    server : Server
    pane_id : str
        For example '%1'.

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

    @property
    def window(self) -> Window:
        """Return the parent :class:`Window` of this pane."""
        assert isinstance(self.window_id, str)
        from libtmux.window import Window

        return Window.from_window_id(server=self.server, window_id=self.window_id)

    @property
    def session(self) -> Session:
        """Return the parent :class:`Session` of this pane."""
        return self.window.session

    #
    # Commands (pane-scoped)
    #
    def cmd(
        self,
        cmd: str,
        *args: t.Any,
        target: str | int | None = None,
    ) -> tmux_cmd:
        """Execute a tmux command in the context of this pane.

        Automatically sets ``-t <pane_id>`` unless overridden by `target`.

        Parameters
        ----------
        cmd
            The tmux subcommand to run (e.g., 'split-window').
        *args
            Additional arguments for the tmux command.
        target, optional
            Custom target. Default is the current pane's ID.

        Returns
        -------
        tmux_cmd
            Result of the tmux command execution.

        Examples
        --------
        >>> pane.cmd('split-window', '-P').stdout[0]
        'libtmux...:...'

        From raw output to an enriched `Pane` object:

        >>> Pane.from_pane_id(
        ...     pane_id=pane.cmd('split-window', '-P', '-F#{pane_id}').stdout[0],
        ...     server=pane.server
        ... )
        Pane(%... Window(@... ...:..., Session($1 libtmux_...)))
        """
        if target is None:
            target = self.pane_id
        return self.server.cmd(cmd, *args, target=target)

    #
    # Commands (tmux-like)
    #
    def resize(
        self,
        /,
        adjustment_direction: ResizeAdjustmentDirection | None = None,
        adjustment: int | None = None,
        height: str | int | None = None,
        width: str | int | None = None,
        zoom: bool | None = None,
        mouse: bool | None = None,
        trim_below: bool | None = None,
    ) -> Pane:
        """Resize this tmux pane.

        Parameters
        ----------
        adjustment_direction : ResizeAdjustmentDirection, optional
            Direction to adjust, ``Up``, ``Down``, ``Left``, ``Right``.
        adjustment : int, optional
            Number of cells to move in the specified direction.
        height : int or str, optional
            ``resize-pane -y`` dimension, e.g. 20 or "50%".
        width : int or str, optional
            ``resize-pane -x`` dimension, e.g. 80 or "25%".
        zoom : bool, optional
            If True, expand (zoom) the pane to occupy the entire window.
        mouse : bool, optional
            If True, resize via mouse (``-M``).
        trim_below : bool, optional
            If True, trim below cursor (``-T``).

        Raises
        ------
        :exc:`exc.LibTmuxException`
            If tmux reports an error.
        :exc:`exc.PaneAdjustmentDirectionRequiresAdjustment`
            If `adjustment_direction` is given but no `adjustment`.
        :exc:`exc.RequiresDigitOrPercentage`
            If a provided dimension is neither a digit nor ends with "%".

        Returns
        -------
        :class:`Pane`
            This pane.

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
        # Manual resizing
        elif height or width:
            if height:
                if isinstance(height, str):
                    if height.endswith("%") and not has_gte_version("3.1"):
                        raise exc.VersionTooLow
                    if not (height.isdigit() or height.endswith("%")):
                        raise exc.RequiresDigitOrPercentage
                tmux_args += (f"-y{height}",)

            if width:
                if isinstance(width, str):
                    if width.endswith("%") and not has_gte_version("3.1"):
                        raise exc.VersionTooLow
                    if not (width.isdigit() or width.endswith("%")):
                        raise exc.RequiresDigitOrPercentage
                tmux_args += (f"-x{width}",)
        # Zoom / Unzoom
        elif zoom:
            tmux_args += ("-Z",)
        # Mouse-based resize
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
    ) -> str | list[str]:
        """Capture text from this pane (``tmux capture-pane -p``).

        ``$ tmux capture-pane -S -10`` etc.

        Parameters
        ----------
        start : int, '-', optional
            Starting line number.
        end : int, '-', optional
            Ending line number.

        Returns
        -------
        str or list[str]
            The captured pane text as a list of lines (by default).

        Examples
        --------
        Basic usage:

        >>> pane.capture_pane()
        [...]
        """
        cmd = ["capture-pane", "-p"]
        if start is not None:
            cmd.extend(["-S", str(start)])
        if end is not None:
            cmd.extend(["-E", str(end)])
        return self.cmd(*cmd).stdout

    def send_keys(
        self,
        cmd: str,
        enter: bool | None = True,
        suppress_history: bool | None = False,
        literal: bool | None = False,
    ) -> None:
        r"""Send keys (as keyboard input) to this pane.

        A leading space character can be added to `cmd` to avoid polluting
        the user's shell history.

        Parameters
        ----------
        cmd : str
            Text or input to send.
        enter : bool, optional
            If True, send Enter after the input (default).
        suppress_history : bool, optional
            If True, prepend a space to the command, preventing it from
            appearing in shell history. Default is False.
        literal : bool, optional
            If True, send keys literally (``-l``). Default is False.

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
    ) -> str | list[str]: ...

    @t.overload
    def display_message(self, cmd: str, get_text: t.Literal[False]) -> None: ...

    def display_message(
        self,
        cmd: str,
        get_text: bool = False,
    ) -> str | list[str] | None:
        """Display or retrieve a message in this pane.

        Uses ``$ tmux display-message``.

        Parameters
        ----------
        cmd : str
            The message or format string to display.
        get_text : bool, optional
            If True, return the text instead of displaying it.

        Returns
        -------
        str, list[str], or None
            The displayed text if `get_text` is True, else None.
        """
        if get_text:
            return self.cmd("display-message", "-p", cmd).stdout
        self.cmd("display-message", cmd)
        return None

    def kill(
        self,
        all_except: bool | None = None,
    ) -> None:
        """Kill this :class:`Pane` (``tmux kill-pane``).

        Parameters
        ----------
        all_except : bool, optional
            If True, kill all panes except this one.

        Raises
        ------
        exc.LibTmuxException
            If tmux reports an error.

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

        proc = self.cmd("kill-pane", *flags)
        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    #
    # "Climber"-helpers
    #
    def select(self) -> Pane:
        """Select this pane (make it the active pane in its window).

        Returns
        -------
        Pane
            This :class:`Pane`.

        Raises
        ------
        exc.LibTmuxException
            If tmux reports an error.

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
        """Select this pane (deprecated).

        .. deprecated:: 0.30
           Use :meth:`.select()`.
        """
        warnings.warn(
            "Pane.select_pane() is deprecated in favor of Pane.select()",
            category=DeprecationWarning,
            stacklevel=2,
        )
        assert isinstance(self.pane_id, str)
        pane = self.window.select_pane(self.pane_id)
        if pane is None:
            raise exc.PaneNotFound(pane_id=self.pane_id)
        return pane

    def split(
        self,
        /,
        target: int | str | None = None,
        start_directory: str | None = None,
        attach: bool = False,
        direction: PaneDirection | None = None,
        full_window_split: bool | None = None,
        zoom: bool | None = None,
        shell: str | None = None,
        size: str | int | None = None,
        environment: dict[str, str] | None = None,
    ) -> Pane:
        """Split this pane, returning a new :class:`Pane`.

        By default, splits beneath the current pane. Specify a direction to
        split horizontally or vertically, a size, and optionally run a shell
        command in the new pane.

        Parameters
        ----------
        target : int or str, optional
            Custom *target-pane*. Defaults to this pane's ID.
        start_directory : str, optional
            Working directory for the new pane.
        attach : bool, optional
            If True, select the new pane immediately (default is False).
        direction : PaneDirection, optional
            Direction to split, e.g. :attr:`PaneDirection.Right`.
        full_window_split : bool, optional
            If True, split across the entire window height/width.
        zoom : bool, optional
            If True, zoom the new pane (``-Z``).
        shell : str, optional
            Command to run immediately in the new pane. The pane closes when
            the command exits.
        size : int or str, optional
            Size for the new pane (cells or percentage).
        environment : dict, optional
            Environment variables for the new pane (tmux 3.0+).

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

        >>> top_pane = pane.split(direction=PaneDirection.Above,
        ...                       full_window_split=True)

        >>> (top_pane.at_left, top_pane.at_right,
        ...  top_pane.at_top, top_pane.at_bottom)
        (True, True,
        True, False)

        >>> bottom_pane = pane.split(
        ...     direction=PaneDirection.Below,
        ...     full_window_split=True)

        >>> (bottom_pane.at_left, bottom_pane.at_right,
        ...  bottom_pane.at_top, bottom_pane.at_bottom)
        (True, True,
        False, True)
        """
        tmux_formats = [f"#{'{'}pane_id{'}'}{FORMAT_SEPARATOR}"]
        tmux_args: tuple[str, ...] = ()

        if direction:
            tmux_args += tuple(PANE_DIRECTION_FLAG_MAP[direction])
        else:
            tmux_args += tuple(PANE_DIRECTION_FLAG_MAP[PaneDirection.Below])

        if size is not None:
            if has_lt_version("3.1"):
                if isinstance(size, str) and size.endswith("%"):
                    tmux_args += (f"-p{str(size).rstrip('%')}",)
                else:
                    warnings.warn(
                        'Ignored size. Use percent in tmux < 3.1, e.g. "50%"',
                        stacklevel=2,
                    )
            else:
                tmux_args += (f"-l{size}",)

        if full_window_split:
            tmux_args += ("-f",)
        if zoom:
            tmux_args += ("-Z",)

        tmux_args += ("-P", "-F{}".format("".join(tmux_formats)))

        if start_directory is not None:
            start_path = pathlib.Path(start_directory).expanduser()
            tmux_args += (f"-c{start_path}",)

        if not attach:
            tmux_args += ("-d",)

        if environment:
            if has_gte_version("3.0"):
                for k, v in environment.items():
                    tmux_args += (f"-e{k}={v}",)
            else:
                logger.warning(
                    "Environment flag ignored, tmux 3.0 or newer required.",
                )

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
        pane_formatters = dict(zip(["pane_id"], pane_output.split(FORMAT_SEPARATOR)))
        return self.from_pane_id(server=self.server, pane_id=pane_formatters["pane_id"])

    #
    # Commands (helpers)
    #
    def set_width(self, width: int) -> Pane:
        """Set pane width in cells."""
        self.resize_pane(width=width)
        return self

    def set_height(self, height: int) -> Pane:
        """Set pane height in cells."""
        self.resize_pane(height=height)
        return self

    def enter(self) -> Pane:
        """Send an Enter keypress to this pane."""
        self.cmd("send-keys", "Enter")
        return self

    def clear(self) -> Pane:
        """Clear the pane by sending 'reset' command."""
        self.send_keys("reset")
        return self

    def reset(self) -> Pane:
        """Reset the pane and clear its history."""
        self.cmd("send-keys", r"-R \; clear-history")
        return self

    #
    # Dunder
    #
    def __eq__(self, other: object) -> bool:
        """Compare two panes by their ``pane_id``."""
        if isinstance(other, Pane):
            return self.pane_id == other.pane_id
        return False

    def __repr__(self) -> str:
        """Return a string representation of this :class:`Pane`."""
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
        start_directory: str | None = None,
        vertical: bool = True,
        shell: str | None = None,
        size: str | int | None = None,
        percent: int | None = None,  # deprecated
        environment: dict[str, str] | None = None,
    ) -> Pane:
        """Split this pane and return the newly created :class:`Pane` (deprecated).

        .. deprecated:: 0.33
           Use :meth:`.split`.

        Parameters
        ----------
        target, optional
            Target for the new pane.
        attach : bool, optional
            If True, select the new pane immediately.
        start_directory : str, optional
            Working directory for the new pane.
        vertical : bool, optional
            If True (default), split vertically (below).
        shell : str, optional
            Command to run in the new pane. Pane closes when command exits.
        size : str or int, optional
            Size for the new pane (cells or percentage).
        percent : int, optional
            If provided, is converted to a string with a trailing '%' for
            older tmux. E.g. '25%'.
        environment : dict[str, str], optional
            Environment variables for the new pane (tmux 3.0+).
        """
        warnings.warn(
            "Pane.split_window() is deprecated in favor of Pane.split()",
            category=DeprecationWarning,
            stacklevel=2,
        )
        if size is None and percent is not None:
            size = f"{str(percent).rstrip('%')}%"
        return self.split(
            target=target,
            attach=attach,
            start_directory=start_directory,
            direction=PaneDirection.Below if vertical else PaneDirection.Right,
            shell=shell,
            size=size,
            environment=environment,
        )

    def get(self, key: str, default: t.Any | None = None) -> t.Any:
        """Return a key-based lookup (deprecated).

        .. deprecated:: 0.16
           Deprecated by attribute lookup, e.g. ``pane.window_name``.
        """
        warnings.warn(
            "Pane.get() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> t.Any:
        """Return an item by key (deprecated).

        .. deprecated:: 0.16
           Deprecated in favor of attributes. e.g. ``pane.window_name``.
        """
        warnings.warn(
            f"Item lookups, e.g. pane['{key}'] is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return getattr(self, key)

    def resize_pane(
        self,
        adjustment_direction: ResizeAdjustmentDirection | None = None,
        adjustment: int | None = None,
        height: str | int | None = None,
        width: str | int | None = None,
        zoom: bool | None = None,
        mouse: bool | None = None,
        trim_below: bool | None = None,
    ) -> Pane:
        """Resize this pane (deprecated).

        .. deprecated:: 0.28
           Use :meth:`.resize`.
        """
        warnings.warn(
            "Deprecated: Use Pane.resize() instead of Pane.resize_pane()",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.resize(
            adjustment_direction=adjustment_direction,
            adjustment=adjustment,
            height=height,
            width=width,
            zoom=zoom,
            mouse=mouse,
            trim_below=trim_below,
        )
