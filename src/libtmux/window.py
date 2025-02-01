"""Pythonization of the :term:`tmux(1)` window.

This module provides the :class:`Window` class, representing a tmux window
capable of containing multiple panes. The class includes methods for splitting,
resizing, renaming, killing, and moving windows, as well as a variety of
property accessors for tmux window attributes.

libtmux.window
~~~~~~~~~~~~~~
"""

from __future__ import annotations

import dataclasses
import logging
import shlex
import typing as t
import warnings

from libtmux._internal.query_list import QueryList
from libtmux.common import has_gte_version, tmux_cmd
from libtmux.constants import (
    RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP,
    PaneDirection,
    ResizeAdjustmentDirection,
    WindowDirection,
)
from libtmux.neo import Obj, fetch_obj, fetch_objs
from libtmux.pane import Pane

from . import exc
from .common import PaneDict, WindowOptionDict, handle_option_error

if t.TYPE_CHECKING:
    import sys
    import types

    from .server import Server
    from .session import Session

    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing_extensions import Self


logger = logging.getLogger(__name__)


@dataclasses.dataclass()
class Window(Obj):
    """Represent a :term:`tmux(1)` window [window_manual]_.

    Holds :class:`Pane` objects.

    Parameters
    ----------
    session : :class:`Session`
        Parent session of this window (conceptual parameter).

    Examples
    --------
    >>> window = session.new_window('My project', attach=True)

    >>> window
    Window(@2 2:My project, Session($... ...))

    Windows have panes:

    >>> window.panes
    [Pane(...)]

    >>> window.active_pane
    Pane(...)

    Relations moving up:

    >>> window.session
    Session(...)

    >>> window.window_id == session.active_window.window_id
    True

    >>> window == session.active_window
    True

    >>> window in session.windows
    True

    The window can be used as a context manager to ensure proper cleanup:

    >>> with session.new_window() as window:
    ...     pane = window.split()
    ...     # Do work with the pane
    ...     # Window will be killed automatically when exiting the context

    References
    ----------
    .. [window_manual] tmux window. openbsd manpage for TMUX(1).
           "Each session has one or more windows linked to it. A window
           occupies the entire screen and may be split into rectangular
           panes..."

       https://man.openbsd.org/tmux.1#DESCRIPTION. Accessed April 1st, 2018.
    """

    server: Server

    def __enter__(self) -> Self:
        """Enter the context, returning self.

        Returns
        -------
        :class:`Window`
            The window instance
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Exit the context, killing the window if it exists.

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
            self.window_id is not None
            and len(self.session.windows.filter(window_id=self.window_id)) > 0
        ):
            self.kill()

    def refresh(self) -> None:
        """Refresh window attributes from tmux."""
        assert isinstance(self.window_id, str)
        return super()._refresh(
            obj_key="window_id",
            obj_id=self.window_id,
            list_cmd="list-windows",
            list_extra_args=("-a",),
        )

    @classmethod
    def from_window_id(cls, server: Server, window_id: str) -> Window:
        """Create a new :class:`Window` from an existing window_id."""
        window = fetch_obj(
            obj_key="window_id",
            obj_id=window_id,
            server=server,
            list_cmd="list-windows",
            list_extra_args=("-a",),
        )
        return cls(server=server, **window)

    @property
    def session(self) -> Session:
        """Return the parent :class:`Session` of this window."""
        assert isinstance(self.session_id, str)
        from libtmux.session import Session

        return Session.from_session_id(server=self.server, session_id=self.session_id)

    @property
    def panes(self) -> QueryList[Pane]:
        """Return a :class:`QueryList` of :class:`Pane` objects contained by window.

        Can be accessed via
        :meth:`.panes.get() <libtmux._internal.query_list.QueryList.get()>` and
        :meth:`.panes.filter() <libtmux._internal.query_list.QueryList.filter()>`
        """
        panes: list[Pane] = [
            Pane(server=self.server, **obj)
            for obj in fetch_objs(
                list_cmd="list-panes",
                list_extra_args=["-t", str(self.window_id)],
                server=self.server,
            )
            if obj.get("window_id") == self.window_id
        ]

        return QueryList(panes)

    # Commands (pane-scoped)

    def cmd(
        self,
        cmd: str,
        *args: t.Any,
        target: str | int | None = None,
    ) -> tmux_cmd:
        """Execute a tmux subcommand within the context of this window.

        Automatically binds ``-t <window_id>`` to the command unless
        overridden by the `target` parameter.

        Parameters
        ----------
        cmd
            The tmux subcommand to execute.
        *args
            Additional arguments for the tmux command.
        target, optional
            Custom target override. By default, the target is this window's ID.

        Examples
        --------
        Create a pane from a window:

        >>> window.cmd('split-window', '-P', '-F#{pane_id}').stdout[0]
        '%...'

        Magic, directly to a `Pane`:

        >>> Pane.from_pane_id(
        ...     pane_id=session.cmd('split-window', '-P', '-F#{pane_id}').stdout[0],
        ...     server=session.server
        ... )
        Pane(%... Window(@... ...:..., Session($1 libtmux_...)))

        Returns
        -------
        tmux_cmd
            The result of the tmux command execution.
        """
        if target is None:
            target = self.window_id

        return self.server.cmd(cmd, *args, target=target)

    # Commands (tmux-like)

    def select_pane(self, target_pane: str | int) -> Pane | None:
        """Select a pane within this window and return the now-active :class:`Pane`.

        Wrapper for ``tmux select-pane``.

        Parameters
        ----------
        target_pane
            Pane specifier (e.g., '-l', '-U', '-D', '-L', '-R', or an ID).

        Returns
        -------
        Pane or None
            The active :class:`Pane` after selection.

        Raises
        ------
        exc.LibTmuxException
            If tmux reports an error (see stderr output).
        """
        if target_pane in {"-l", "-U", "-D", "-L", "-R"}:
            proc = self.cmd("select-pane", target_pane)
        else:
            proc = self.cmd("select-pane", target=target_pane)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        return self.active_pane

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
        """Split the active pane in this window and return newly created :class:`Pane`.

        Parameters
        ----------
        target, optional
            Custom target override (defaults to the active pane in this window).
        start_directory, optional
            Working directory in which to create the new pane.
        attach, optional
            Whether to make the new pane the current pane. Default is False.
        direction, optional
            Direction in which to split. Defaults to splitting downwards.
        full_window_split, optional
            If True, split across the full window width/height rather than active pane.
        zoom, optional
            Whether to zoom (expand) the newly created pane.
        shell, optional
            Shell command to execute immediately in the new pane. The pane
            closes when the command exits.
        size, optional
            Size of the new pane (cells/rows or a percentage). Example: "50%", 10, etc.
        environment, optional
            Dictionary of environment variables for the new pane (tmux 3.0+).

        Returns
        -------
        Pane
            The newly created pane object.
        """
        active_pane = self.active_pane or self.panes[0]
        return active_pane.split(
            target=target,
            start_directory=start_directory,
            attach=attach,
            direction=direction,
            full_window_split=full_window_split,
            zoom=zoom,
            shell=shell,
            size=size,
            environment=environment,
        )

    def resize(
        self,
        /,
        adjustment_direction: ResizeAdjustmentDirection | None = None,
        adjustment: int | None = None,
        height: int | None = None,
        width: int | None = None,
        expand: bool | None = None,
        shrink: bool | None = None,
    ) -> Window:
        """Resize this tmux window.

        This method supports three types of resizing:
          1. Adjustments (direction + amount)
          2. Manual resizing (explicit height or width)
          3. Expand or shrink (full window)

        Parameters
        ----------
        adjustment_direction, optional
            Direction to adjust (Up, Down, Left, Right).
        adjustment, optional
            Number of cells/rows to adjust in the given direction.
        height, optional
            Set the window height (in cells).
        width, optional
            Set the window width (in cells).
        expand, optional
            Expand the window to the maximum size.
        shrink, optional
            Shrink the window to the minimum size.

        Returns
        -------
        Window
            This :class:`Window` instance (for chaining).

        Raises
        ------
        exc.LibTmuxException
            If tmux reports an error (see stderr).
        exc.WindowAdjustmentDirectionRequiresAdjustment
            If `adjustment_direction` is given but `adjustment` is None.

        Notes
        -----
        This method requires tmux 2.9 or newer.
        """
        if not has_gte_version("2.9"):
            warnings.warn("resize() requires tmux 2.9 or newer", stacklevel=2)
            return self

        tmux_args: tuple[str, ...] = ()

        # Adjustments
        if adjustment_direction:
            if adjustment is None:
                raise exc.WindowAdjustmentDirectionRequiresAdjustment
            tmux_args += (
                f"{RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP[adjustment_direction]}",
                str(adjustment),
            )
        elif height or width:
            # Manual resizing
            if height:
                tmux_args += (f"-y{int(height)}",)
            if width:
                tmux_args += (f"-x{int(width)}",)
        elif expand or shrink:
            if expand:
                tmux_args += ("-A",)
            elif shrink:
                tmux_args += ("-a",)

        proc = self.cmd("resize-window", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        self.refresh()
        return self

    def last_pane(self) -> Pane | None:
        """Select and return the last active :class:`Pane` in this window.

        Wrapper for ``tmux select-pane -l``.

        Returns
        -------
        Pane or None
            The newly selected active pane, or None if none found.
        """
        return self.select_pane("-l")

    def select_layout(self, layout: str | None = None) -> Window:
        """Select a layout for this window.

        Wrapper for ``tmux select-layout <layout>``.

        Parameters
        ----------
        layout, optional
            The layout name (e.g. 'even-horizontal', 'tiled'). If None,
            tmux will use the most recently set layout.

        Returns
        -------
        Window
            This :class:`Window` instance (for chaining).

        Raises
        ------
        exc.LibTmuxException
            If tmux reports an error (see stderr).
        """
        cmd = ["select-layout"]
        if layout:
            cmd.append(layout)

        proc = self.cmd(*cmd)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        return self

    def set_window_option(self, option: str, value: int | str) -> Window:
        """Set a tmux window option.

        Wrapper for ``tmux set-window-option <option> <value>``.

        Parameters
        ----------
        option
            Name of the tmux window option (e.g. 'aggressive-resize').
        value
            The value for this window option. A bool `True` becomes 'on';
            `False` becomes 'off'.

        Returns
        -------
        Window
            This :class:`Window` instance (for chaining).

        Raises
        ------
        exc.OptionError
            If tmux indicates a problem setting the option.
        exc.UnknownOption
        exc.InvalidOption
        exc.AmbiguousOption
        """
        if isinstance(value, bool):
            value = "on" if value else "off"

        cmd_result = self.cmd("set-window-option", option, value)

        if isinstance(cmd_result.stderr, list) and len(cmd_result.stderr):
            handle_option_error(cmd_result.stderr[0])

        return self

    def show_window_options(self, g: bool | None = False) -> WindowOptionDict:
        """Return a dictionary of options for this window.

        Wrapper for ``tmux show-window-options``.

        Parameters
        ----------
        g, optional
            If True, show global window options (``-g`` flag).

        Returns
        -------
        WindowOptionDict
            Dictionary of window options (key-value pairs).
        """
        tmux_args: tuple[str, ...] = ()
        if g:
            tmux_args += ("-g",)
        tmux_args += ("show-window-options",)

        cmd_result = self.cmd(*tmux_args)
        output = cmd_result.stdout

        window_options: WindowOptionDict = {}
        for item in output:
            try:
                key, val = shlex.split(item)
            except ValueError:
                logger.exception(f"Error extracting option: {item}")
                continue

            if val.isdigit():
                window_options[key] = int(val)
            else:
                window_options[key] = val

        return window_options

    def show_window_option(self, option: str, g: bool = False) -> str | int | None:
        """Return the value of a specific window option.

        Wrapper for ``tmux show-window-options <option>``.

        Parameters
        ----------
        option
            Name of the option to retrieve.
        g, optional
            If True, show a global window option instead of local.

        Returns
        -------
        str or int or None
            Value of the requested option, or None if not set.

        Raises
        ------
        exc.OptionError
        exc.UnknownOption
        exc.InvalidOption
        exc.AmbiguousOption
        """
        tmux_args: tuple[str | int, ...] = ()
        if g:
            tmux_args += ("-g",)
        tmux_args += (option,)

        cmd_result = self.cmd("show-window-options", *tmux_args)

        if cmd_result.stderr:
            handle_option_error(cmd_result.stderr[0])

        window_options_output = cmd_result.stdout
        if not window_options_output:
            return None

        value_raw = next(shlex.split(item) for item in window_options_output)
        value: str | int = int(value_raw[1]) if value_raw[1].isdigit() else value_raw[1]
        return value

    def rename_window(self, new_name: str) -> Window:
        """Rename this window.

        Wrapper for ``tmux rename-window <new_name>``.

        Parameters
        ----------
        new_name
            The new name of the window.

        Returns
        -------
        Window
            This :class:`Window` instance (for chaining).

        Examples
        --------
        >>> window = session.active_window
        >>> window.rename_window('My project')
        Window(@1 1:My project, Session($1 ...))

        >>> window.rename_window('New name')
        Window(@1 1:New name, Session($1 ...))
        """
        import shlex

        lex = shlex.shlex(new_name)
        lex.escape = " "
        lex.whitespace_split = False

        try:
            self.cmd("rename-window", new_name)
            self.window_name = new_name
        except Exception:
            logger.exception(f"Error renaming window to {new_name}")

        self.refresh()
        return self

    def kill(self, all_except: bool | None = None) -> None:
        """Kill this window.

        Wrapper for ``tmux kill-window``.

        Parameters
        ----------
        all_except, optional
            If True, kill all windows except the current one.

        Examples
        --------
        Kill a window:

        >>> window_1 = session.new_window()
        >>> window_1 in session.windows
        True
        >>> window_1.kill()
        >>> window_1 not in session.windows
        True

        Kill all windows except the current one:

        >>> one_window_to_rule_them_all = session.new_window()
        >>> other_windows = session.new_window(), session.new_window()
        >>> all([w in session.windows for w in other_windows])
        True

        >>> one_window_to_rule_them_all.kill(all_except=True)
        >>> all([w not in session.windows for w in other_windows])
        True

        >>> one_window_to_rule_them_all in session.windows
        True

        Raises
        ------
        exc.LibTmuxException
            If tmux reports an error (see stderr).
        """
        flags: tuple[str, ...] = ()
        if all_except:
            flags += ("-a",)

        proc = self.cmd("kill-window", *flags)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def move_window(
        self,
        destination: str = "",
        session: str | None = None,
    ) -> Window:
        """Move the current window to a new location.

        Wrapper for ``tmux move-window``.

        Parameters
        ----------
        destination, optional
            The target window or index to move this window to. Defaults to "".
        session, optional
            The target session to move the window to. Defaults to the current session.

        Returns
        -------
        Window
            This :class:`Window` instance (for chaining).

        Raises
        ------
        exc.LibTmuxException
            If tmux reports an error (see stderr).
        """
        session = session or self.session_id
        proc = self.cmd(
            "move-window",
            f"-s{self.session_id}:{self.window_index}",
            target=f"{session}:{destination}",
        )

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        if destination != "" and session is not None:
            self.window_index = destination
        else:
            self.refresh()

        return self

    def new_window(
        self,
        window_name: str | None = None,
        *,
        start_directory: None = None,
        attach: bool = False,
        window_index: str = "",
        window_shell: str | None = None,
        environment: dict[str, str] | None = None,
        direction: WindowDirection | None = None,
    ) -> Window:
        """Create new window before or after this window, returning :class:`Window`.

        See Also
        --------
        Session.new_window : More detailed parameter definitions.

        Examples
        --------
        .. ::
            >>> import pytest
            >>> from libtmux.common import has_lt_version
            >>> if has_lt_version('3.2'):
            ...     pytest.skip('This doctest requires tmux 3.2 or newer')

        >>> window_initial = session.new_window(window_name='Example')
        >>> window_initial
        Window(@... 2:Example, Session($1 libtmux_...))
        >>> window_initial.window_index
        '2'

        >>> window_before = window_initial.new_window(
        ...     window_name='Window before',
        ...     direction=WindowDirection.Before
        ... )
        >>> window_initial.refresh()
        >>> window_before
        Window(@... 2:Window before, Session($1 libtmux_...))
        >>> window_initial
        Window(@... 3:Example, Session($1 libtmux_...))

        >>> window_after = window_initial.new_window(
        ...     window_name='Window after',
        ...     direction=WindowDirection.After
        ... )
        >>> window_initial.refresh()
        >>> window_after.refresh()
        >>> window_after
        Window(@... 4:Window after, Session($1 libtmux_...))
        >>> window_initial
        Window(@... 3:Example, Session($1 libtmux_...))
        >>> window_before
        Window(@... 2:Window before, Session($1 libtmux_...))
        """
        return self.session.new_window(
            window_name=window_name,
            start_directory=start_directory,
            attach=attach,
            window_index=window_index,
            window_shell=window_shell,
            environment=environment,
            direction=direction,
            target_window=self.window_id,
        )

    def select(self) -> Window:
        """Select this window (make it the active window in its session).

        Wrapper for ``tmux select-window``.

        Returns
        -------
        Window
            This :class:`Window` instance (for chaining).

        Raises
        ------
        exc.LibTmuxException
            If tmux reports an error (see stderr).

        Examples
        --------
        >>> window = session.active_window
        >>> new_window = session.new_window()
        >>> session.refresh()
        >>> new_window.window_active == '1'
        False

        >>> new_window.select()
        Window(...)

        >>> new_window.window_active == '1'
        True
        """
        proc = self.cmd("select-window")
        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)
        self.refresh()
        return self

    @property
    def active_pane(self) -> Pane | None:
        """Return the currently active :class:`Pane` in this window."""
        panes = self.panes.filter(pane_active="1")
        if len(panes) > 0:
            return panes[0]
        return None

    def __eq__(self, other: object) -> bool:
        """Compare windows by ``window_id``."""
        if isinstance(other, Window):
            return self.window_id == other.window_id
        return False

    def __repr__(self) -> str:
        """Return a string representation of this :class:`Window`."""
        return (
            f"{self.__class__.__name__}({self.window_id} "
            f"{self.window_index}:{self.window_name}, {self.session})"
        )

    # Aliases

    @property
    def id(self) -> str | None:
        """Alias of :attr:`Window.window_id`.

        Examples
        --------
        >>> window.id
        '@1'

        >>> window.id == window.window_id
        True
        """
        return self.window_id

    @property
    def name(self) -> str | None:
        """Alias of :attr:`Window.window_name`.

        Examples
        --------
        >>> window.name
        '...'

        >>> window.name == window.window_name
        True
        """
        return self.window_name

    @property
    def index(self) -> str | None:
        """Alias of :attr:`Window.window_index`.

        Examples
        --------
        >>> window.index
        '1'

        >>> window.index == window.window_index
        True
        """
        return self.window_index

    @property
    def height(self) -> str | None:
        """Alias of :attr:`Window.window_height`.

        Examples
        --------
        >>> window.height.isdigit()
        True

        >>> window.height == window.window_height
        True
        """
        return self.window_height

    @property
    def width(self) -> str | None:
        """Alias of :attr:`Window.window_width`.

        Examples
        --------
        >>> window.width.isdigit()
        True

        >>> window.width == window.window_width
        True
        """
        return self.window_width

    # Deprecated / Legacy Methods

    def split_window(
        self,
        target: int | str | None = None,
        start_directory: str | None = None,
        attach: bool = False,
        vertical: bool = True,
        shell: str | None = None,
        size: str | int | None = None,
        percent: int | None = None,
        environment: dict[str, str] | None = None,
    ) -> Pane:
        """Split window (deprecated).

        .. deprecated:: 0.33.0
           Use :meth:`.split()` instead.

        .. versionchanged:: 0.28.0
           ``attach`` default changed from ``True`` to ``False``.

        .. deprecated:: 0.28.0
           ``percent=25`` replaced by size="25%".

        """
        warnings.warn(
            "Window.split_window() is deprecated in favor of Window.split()",
            category=DeprecationWarning,
            stacklevel=2,
        )

        if percent is not None:
            warnings.warn(
                f'Deprecated in favor of size="{str(percent).rstrip("%")}%" '
                ' ("-l" flag) in tmux 3.1+.',
                category=DeprecationWarning,
                stacklevel=2,
            )
            if size is None:
                size = f"{str(percent).rstrip('%')}%"

        return self.split(
            target=target,
            start_directory=start_directory,
            attach=attach,
            direction=PaneDirection.Below if vertical else PaneDirection.Right,
            shell=shell,
            size=size,
            environment=environment,
        )

    @property
    def attached_pane(self) -> Pane | None:
        """Return the attached pane (deprecated).

        .. deprecated:: 0.31
           Use :meth:`.active_pane`.
        """
        warnings.warn(
            "Window.attached_pane() is deprecated in favor of Window.active_pane()",
            category=DeprecationWarning,
            stacklevel=2,
        )
        panes = self.panes.filter(pane_active="1")
        if len(panes) > 0:
            return panes[0]
        return None

    def select_window(self) -> Window:
        """Select this window (deprecated).

        .. deprecated:: 0.30
           Use :meth:`.select()`.
        """
        warnings.warn(
            "Window.select_window() is deprecated in favor of Window.select()",
            category=DeprecationWarning,
            stacklevel=2,
        )
        assert isinstance(self.window_index, str)
        return self.session.select_window(self.window_index)

    def kill_window(self) -> None:
        """Kill this window (deprecated).

        .. deprecated:: 0.30
           Use :meth:`.kill()`.
        """
        warnings.warn(
            "Window.kill_window() is deprecated in favor of Window.kill()",
            category=DeprecationWarning,
            stacklevel=2,
        )
        proc = self.cmd("kill-window")
        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def get(self, key: str, default: t.Any | None = None) -> t.Any:
        """Return a value by key lookup (deprecated).

        .. deprecated:: 0.16
           Use attribute lookup. E.g. `window.window_name`.
        """
        warnings.warn(
            "Window.get() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> t.Any:
        """Return a value by item lookup (deprecated).

        .. deprecated:: 0.16
           Use attribute lookup. E.g. `window.window_name`.
        """
        warnings.warn(
            f"Item lookups, e.g. window['{key}'] is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return getattr(self, key)

    def get_by_id(self, pane_id: str) -> Pane | None:
        """Return a :class:`Pane` by ID (deprecated).

        .. deprecated:: 0.16
           Use :meth:`.panes.get()`.
        """
        warnings.warn(
            "Window.get_by_id() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.panes.get(pane_id=pane_id, default=None)

    def where(self, kwargs: dict[str, t.Any]) -> list[Pane]:
        """Filter through panes by criteria (deprecated).

        .. deprecated:: 0.16
           Use :meth:`.panes.filter()`.
        """
        warnings.warn(
            "Window.where() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        try:
            return self.panes.filter(**kwargs)
        except IndexError:
            return []

    def find_where(self, kwargs: dict[str, t.Any]) -> Pane | None:
        """Return the first matching :class:`Pane` (deprecated).

        .. deprecated:: 0.16
           Use :meth:`.panes.get()`.
        """
        warnings.warn(
            "Window.find_where() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.panes.get(default=None, **kwargs)

    def _list_panes(self) -> list[PaneDict]:
        """Return a list of pane dictionaries (deprecated).

        .. deprecated:: 0.16
           Use :attr:`.panes`.
        """
        warnings.warn(
            "Window._list_panes() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return [pane.__dict__ for pane in self.panes]

    @property
    def _panes(self) -> list[PaneDict]:
        """Alias to :meth:`._list_panes` (deprecated).

        .. deprecated:: 0.16
           Use :attr:`.panes`.
        """
        warnings.warn("_panes is deprecated", category=DeprecationWarning, stacklevel=2)
        return self._list_panes()

    def list_panes(self) -> list[Pane]:
        """Return a list of :class:`Pane` objects (deprecated).

        .. deprecated:: 0.16
           Use :attr:`.panes`.
        """
        warnings.warn(
            "list_panes() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.panes

    @property
    def children(self) -> QueryList[Pane]:
        """Return child panes (deprecated).

        .. deprecated:: 0.16
           Use :attr:`.panes`.
        """
        warnings.warn(
            "Window.children is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.panes
