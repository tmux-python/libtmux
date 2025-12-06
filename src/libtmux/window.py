"""Pythonization of the :term:`tmux(1)` window.

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
from libtmux.common import tmux_cmd
from libtmux.constants import (
    RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP,
    OptionScope,
    PaneDirection,
    ResizeAdjustmentDirection,
    WindowDirection,
)
from libtmux.hooks import HooksMixin
from libtmux.neo import Obj, fetch_obj, fetch_objs
from libtmux.pane import Pane

from . import exc
from .common import PaneDict, WindowOptionDict
from .options import OptionsMixin

if t.TYPE_CHECKING:
    import sys
    import types

    from libtmux._internal.types import StrPath

    from .common import PaneDict, WindowOptionDict
    from .server import Server
    from .session import Session

    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing_extensions import Self


logger = logging.getLogger(__name__)


@dataclasses.dataclass()
class Window(
    Obj,
    OptionsMixin,
    HooksMixin,
):
    """:term:`tmux(1)` :term:`Window` [window_manual]_.

    Holds :class:`Pane` objects.

    Parameters
    ----------
    session : :class:`Session`

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

    default_option_scope: OptionScope | None = OptionScope.Window
    default_hook_scope: OptionScope | None = OptionScope.Window
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
        """Create Window from existing window_id."""
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
        """Parent session of window."""
        assert isinstance(self.session_id, str)
        from libtmux.session import Session

        return Session.from_session_id(server=self.server, session_id=self.session_id)

    @property
    def panes(self) -> QueryList[Pane]:
        """Panes contained by window.

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

    """
    Commands (pane-scoped)
    """

    def cmd(
        self,
        cmd: str,
        *args: t.Any,
        target: str | int | None = None,
    ) -> tmux_cmd:
        """Execute tmux subcommand within window context.

        Automatically binds target by adding  ``-t`` for object's window ID to the
        command. Pass ``target`` to keyword arguments to override.

        Examples
        --------
        Create a pane from a window:

        >>> window.cmd('split-window', '-P', '-F#{pane_id}').stdout[0]
        '%...'

        Magic, directly to a `Pane`:

        >>> Pane.from_pane_id(pane_id=session.cmd(
        ... 'split-window', '-P', '-F#{pane_id}').stdout[0], server=session.server)
        Pane(%... Window(@... ...:..., Session($1 libtmux_...)))

        Parameters
        ----------
        target : str, optional
            Optional custom target override. By default, the target is the window ID.

        Returns
        -------
        :meth:`server.cmd`
        """
        if target is None:
            target = self.window_id

        return self.server.cmd(cmd, *args, target=target)

    """
    Commands (tmux-like)
    """

    def select_pane(self, target_pane: str | int) -> Pane | None:
        """Select pane and return selected :class:`Pane`.

        ``$ tmux select-pane``.

        Parameters
        ----------
        target_pane : str
            'target_pane', '-U' ,'-D', '-L', '-R', or '-l'.

        Returns
        -------
        :class:`Pane`
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
        start_directory: StrPath | None = None,
        attach: bool = False,
        direction: PaneDirection | None = None,
        full_window_split: bool | None = None,
        zoom: bool | None = None,
        shell: str | None = None,
        size: str | int | None = None,
        environment: dict[str, str] | None = None,
    ) -> Pane:
        """Split window on active pane and return the created :class:`Pane`.

        Parameters
        ----------
        attach : bool, optional
            Make new window the current window after creating it, default
            True.
        start_directory : str or PathLike, optional
            Specifies the working directory in which the new window is created.
        direction : PaneDirection, optional
            Split in direction. If none is specified, assume down.
        full_window_split : bool, optional
            Split across full window width or height, rather than active pane.
        zoom : bool, optional
            Expand pane.
        shell : str, optional
            Execute a command on splitting the window. The pane will close
            when the command exits.

            NOTE: When this command exits the pane will close. This feature
            is useful for long-running processes where the closing of the
            window upon completion is desired.
        size : int, optional
            Cell/row or percentage to occupy with respect to current window.
        environment : dict, optional
            Environmental variables for new pane. Passthrough to ``-e``.

        Returns
        -------
        :class:`Pane`
            The newly created pane.
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
        # Adjustments
        adjustment_direction: ResizeAdjustmentDirection | None = None,
        adjustment: int | None = None,
        # Manual
        height: int | None = None,
        width: int | None = None,
        # Expand / Shrink
        expand: bool | None = None,
        shrink: bool | None = None,
    ) -> Window:
        """Resize tmux window.

        Parameters
        ----------
        adjustment_direction : ResizeAdjustmentDirection, optional
            direction to adjust, ``Up``, ``Down``, ``Left``, ``Right``.
        adjustment : ResizeAdjustmentDirection, optional

        height : int, optional
            ``resize-window -y`` dimensions
        width : int, optional
            ``resize-window -x`` dimensions

        expand : bool
            expand window
        shrink : bool
            shrink window

        Raises
        ------
        :exc:`exc.LibTmuxException`,
        :exc:`exc.PaneAdjustmentDirectionRequiresAdjustment`

        Returns
        -------
        :class:`Window`

        Notes
        -----
        Three types of resizing are available:

        1. Adjustments: ``adjustment_direction`` and ``adjustment``.
        2. Manual resizing: ``height`` and / or ``width``.
        3. Expand or shrink: ``expand`` or ``shrink``.
        """
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
        """Return last pane."""
        return self.select_pane("-l")

    def select_layout(self, layout: str | None = None) -> Window:
        """Select layout for window.

        Wrapper for ``$ tmux select-layout <layout>``.

        Parameters
        ----------
        layout : str, optional
            String of the layout, 'even-horizontal', 'tiled', etc. Entering
            None (leaving this blank) is same as ``select-layout`` with no
            layout. In recent tmux versions, it picks the most recently
            set layout.

            'even-horizontal'
                Panes are spread out evenly from left to right across the
                window.
            'even-vertical'
                Panes are spread evenly from top to bottom.
            'main-horizontal'
                A large (main) pane is shown at the top of the window and the
                remaining panes are spread from left to right in the leftover
                space at the bottom.
            'main-vertical'
                Similar to main-horizontal but the large pane is placed on the
                left and the others spread from top to bottom along the right.
            'tiled'
                Panes are spread out as evenly as possible over the window in
                both rows and columns.
            'custom'
                Custom dimensions (see :term:`tmux(1)` manpages).

        Returns
        -------
        :class:`Window`
            Self, for method chaining.

        Raises
        ------
        :exc:`libtmux.exc.LibTmuxException`
            If tmux returns an error.
        """
        cmd = ["select-layout"]

        if layout:  # tmux allows select-layout without args
            cmd.append(layout)

        proc = self.cmd(*cmd)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        return self

    def rename_window(self, new_name: str) -> Window:
        """Rename window.

        Parameters
        ----------
        new_name : str
            name of the window

        Examples
        --------
        >>> window = session.active_window

        >>> window.rename_window('My project')
        Window(@1 1:My project, Session($1 ...))

        >>> window.rename_window('New name')
        Window(@1 1:New name, Session($1 ...))
        """
        lex = shlex.shlex(new_name)
        lex.escape = " "
        lex.whitespace_split = False

        try:
            self.cmd("rename-window", new_name)
            self.window_name = new_name
        except Exception:
            logger.exception("Error renaming window to %s", new_name)

        self.refresh()

        return self

    def kill(
        self,
        all_except: bool | None = None,
    ) -> None:
        """Kill :class:`Window`.

        ``$ tmux kill-window``.

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

        >>> other_windows = session.new_window(
        ...     ), session.new_window()

        >>> all([w in session.windows for w in other_windows])
        True

        >>> one_window_to_rule_them_all.kill(all_except=True)

        >>> all([w not in session.windows for w in other_windows])
        True

        >>> one_window_to_rule_them_all in session.windows
        True
        """
        flags: tuple[str, ...] = ()

        if all_except:
            flags += ("-a",)

        proc = self.cmd(
            "kill-window",
            *flags,
        )

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def move_window(
        self,
        destination: str = "",
        session: str | None = None,
    ) -> Window:
        """Move current :class:`Window` object ``$ tmux move-window``.

        Parameters
        ----------
        destination : str, optional
            The ``target window`` or index to move the window to, default:
            empty string.
        session : str, optional
            The ``target session`` or index to move the window to, default:
            current session.

        Returns
        -------
        :class:`Window`
            Self, for method chaining.

        Raises
        ------
        :exc:`libtmux.exc.LibTmuxException`
            If tmux returns an error.
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
        """Create new window respective of current window's position.

        See Also
        --------
        :meth:`Session.new_window()`

        Examples
        --------
        >>> window_initial = session.new_window(window_name='Example')
        >>> window_initial
        Window(@... 2:Example, Session($1 libtmux_...))
        >>> window_initial.window_index
        '2'

        >>> window_before = window_initial.new_window(
        ... window_name='Window before', direction=WindowDirection.Before)
        >>> window_initial.refresh()
        >>> window_before
        Window(@... 2:Window before, Session($1 libtmux_...))
        >>> window_initial
        Window(@... 3:Example, Session($1 libtmux_...))

        >>> window_after = window_initial.new_window(
        ... window_name='Window after', direction=WindowDirection.After)
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

    #
    # Climbers
    #
    def select(self) -> Window:
        """Select window.

        To select a window object asynchrously. If a ``window`` object exists
        and is no longer the current window, ``w.select_window()``
        will make ``w`` the current window.

        Examples
        --------
        >>> window = session.active_window
        >>> new_window = session.new_window()
        >>> session.refresh()
        >>> active_windows = [w for w in session.windows if w.window_active == '1']

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

    #
    # Computed properties
    #
    @property
    def active_pane(self) -> Pane | None:
        """Return attached :class:`Pane`."""
        panes = self.panes.filter(pane_active="1")
        if len(panes) > 0:
            return panes[0]
        return None

    #
    # Dunder
    #
    def __eq__(self, other: object) -> bool:
        """Equal operator for :class:`Window` object."""
        if isinstance(other, Window):
            return self.window_id == other.window_id
        return False

    def __repr__(self) -> str:
        """Representation of :class:`Window` object."""
        return (
            f"{self.__class__.__name__}({self.window_id} "
            f"{self.window_index}:{self.window_name}, {self.session})"
        )

    #
    # Aliases
    #
    @property
    def id(self) -> str | None:
        """Alias of :attr:`Window.window_id`.

        >>> window.id
        '@1'

        >>> window.id == window.window_id
        True
        """
        return self.window_id

    @property
    def name(self) -> str | None:
        """Alias of :attr:`Window.window_name`.

        >>> window.name
        '...'

        >>> window.name == window.window_name
        True
        """
        return self.window_name

    @property
    def index(self) -> str | None:
        """Alias of :attr:`Window.window_index`.

        >>> window.index
        '1'

        >>> window.index == window.window_index
        True
        """
        return self.window_index

    @property
    def height(self) -> str | None:
        """Alias of :attr:`Window.window_height`.

        >>> window.height.isdigit()
        True

        >>> window.height == window.window_height
        True
        """
        return self.window_height

    @property
    def width(self) -> str | None:
        """Alias of :attr:`Window.window_width`.

        >>> window.width.isdigit()
        True

        >>> window.width == window.window_width
        True
        """
        return self.window_width

    #
    # Legacy: Redundant stuff we want to remove
    #
    def split_window(
        self,
        target: int | str | None = None,
        start_directory: StrPath | None = None,
        attach: bool = False,
        vertical: bool = True,
        shell: str | None = None,
        size: str | int | None = None,
        percent: int | None = None,  # deprecated
        environment: dict[str, str] | None = None,
    ) -> Pane:
        """Split window and return the created :class:`Pane`.

        Notes
        -----
        .. deprecated:: 0.33.0

           Deprecated in favor of :meth:`.split()`.

        .. versionchanged:: 0.28.0

           ``attach`` default changed from ``True`` to ``False``.

        .. deprecated:: 0.28.0

           ``percent=25`` deprecated in favor of ``size="25%"``.
        """
        raise exc.DeprecatedError(
            deprecated="Window.split_window()",
            replacement="Window.split()",
            version="0.33.0",
        )

    @property
    def attached_pane(self) -> Pane | None:
        """Return attached :class:`Pane`.

        Notes
        -----
        .. deprecated:: 0.31

           Deprecated in favor of :meth:`.active_pane`.
        """
        raise exc.DeprecatedError(
            deprecated="Window.attached_pane",
            replacement="Window.active_pane",
            version="0.31.0",
        )

    def select_window(self) -> Window:
        """Select window.

        Notes
        -----
        .. deprecated:: 0.30

           Deprecated in favor of :meth:`.select()`.
        """
        raise exc.DeprecatedError(
            deprecated="Window.select_window()",
            replacement="Window.select()",
            version="0.30.0",
        )

    def kill_window(self) -> None:
        """Kill the current :class:`Window` object. ``$ tmux kill-window``.

        Notes
        -----
        .. deprecated:: 0.30

           Deprecated in favor of :meth:`.kill()`.
        """
        raise exc.DeprecatedError(
            deprecated="Window.kill_window()",
            replacement="Window.kill()",
            version="0.30.0",
        )

    def set_window_option(
        self,
        option: str,
        value: int | str,
    ) -> Window:
        """Set option for tmux window. Deprecated by :meth:`Window.set_option()`.

        .. deprecated:: 0.50

           Deprecated by :meth:`Window.set_option()`.

        """
        warnings.warn(
            "Window.set_window_option() is deprecated in favor of Window.set_option()",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.set_option(option=option, value=value)

    def show_window_options(self, g: bool | None = False) -> WindowOptionDict:
        """Show options for tmux window. Deprecated by :meth:`Window.show_options()`.

        .. deprecated:: 0.50

           Deprecated by :meth:`Window.show_options()`.

        """
        warnings.warn(
            "Window.show_window_options() is deprecated"
            " in favor of Window.show_options()",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.show_options(
            global_=g or False,
            scope=OptionScope.Window,
        )

    def show_window_option(
        self,
        option: str,
        g: bool = False,
    ) -> str | int | None:
        """Return option for target window. Deprecated by :meth:`Window.show_option()`.

        .. deprecated:: 0.50

           Deprecated by :meth:`Window.show_option()`.

        """
        warnings.warn(
            "Window.show_window_option() is deprecated"
            " in favor of Window.show_option()",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.show_option(
            option=option,
            global_=g,
        )

    def get(self, key: str, default: t.Any | None = None) -> t.Any:
        """Return key-based lookup. Deprecated by attributes.

        .. deprecated:: 0.17

           Deprecated by attribute lookup.e.g. ``window['window_name']`` is now
           accessed via ``window.window_name``.

        """
        raise exc.DeprecatedError(
            deprecated="Window.get()",
            replacement="direct attribute access (e.g., window.window_name)",
            version="0.17.0",
        )

    def __getitem__(self, key: str) -> t.Any:
        """Return item lookup by key. Deprecated in favor of attributes.

        .. deprecated:: 0.17

           Deprecated in favor of attributes. e.g. ``window['window_name']`` is now
           accessed via ``window.window_name``.

        """
        raise exc.DeprecatedError(
            deprecated="Window[key] lookup",
            replacement="direct attribute access (e.g., window.window_name)",
            version="0.17.0",
        )

    def get_by_id(self, pane_id: str) -> Pane | None:
        """Return pane by id. Deprecated in favor of :meth:`.panes.get()`.

        .. deprecated:: 0.16

           Deprecated by :meth:`.panes.get()`.

        """
        raise exc.DeprecatedError(
            deprecated="Window.get_by_id()",
            replacement="Window.panes.get(pane_id=..., default=None)",
            version="0.16.0",
        )

    def where(self, kwargs: dict[str, t.Any]) -> list[Pane]:
        """Filter through panes, return list of :class:`Pane`.

        .. deprecated:: 0.17

           Deprecated by :meth:`.panes.filter()`.

        """
        raise exc.DeprecatedError(
            deprecated="Window.where()",
            replacement="Window.panes.filter()",
            version="0.17.0",
        )

    def find_where(self, kwargs: dict[str, t.Any]) -> Pane | None:
        """Filter through panes, return first :class:`Pane`.

        .. deprecated:: 0.17

           Slated to be removed in favor of :meth:`.panes.get()`.

        """
        raise exc.DeprecatedError(
            deprecated="Window.find_where()",
            replacement="Window.panes.get(default=None, **kwargs)",
            version="0.17.0",
        )

    def _list_panes(self) -> list[PaneDict]:
        """Return list of panes (deprecated in favor of :meth:`.panes`).

        .. deprecated:: 0.17

           Slated to be removed in favor of :attr:`.panes`.

        """
        raise exc.DeprecatedError(
            deprecated="Window._list_panes()",
            replacement="Window.panes property",
            version="0.17.0",
        )

    @property
    def _panes(self) -> list[PaneDict]:
        """Property / alias to return :meth:`~._list_panes`.

        .. deprecated:: 0.17

           Slated to be removed in favor of :attr:`.panes`.

        """
        raise exc.DeprecatedError(
            deprecated="Window._panes",
            replacement="Window.panes property",
            version="0.17.0",
        )

    def list_panes(self) -> list[Pane]:
        """Return list of :class:`Pane` for the window.

        .. deprecated:: 0.17

           Slated to be removed in favor of :attr:`.panes`.

        """
        raise exc.DeprecatedError(
            deprecated="Window.list_panes()",
            replacement="Window.panes property",
            version="0.17.0",
        )

    @property
    def children(self) -> QueryList[Pane]:
        """Was used by TmuxRelationalObject (but that's longer used in this class).

        .. deprecated:: 0.17

           Slated to be removed in favor of :attr:`.panes`.

        """
        raise exc.DeprecatedError(
            deprecated="Window.children",
            replacement="Window.panes property",
            version="0.17.0",
        )
