"""Pythonization of the :term:`tmux(1)` window.

libtmux.window
~~~~~~~~~~~~~~

"""

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
    from .server import Server
    from .session import Session

logger = logging.getLogger(__name__)


@dataclasses.dataclass()
class Window(Obj):
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

    References
    ----------
    .. [window_manual] tmux window. openbsd manpage for TMUX(1).
           "Each session has one or more windows linked to it. A window
           occupies the entire screen and may be split into rectangular
           panes..."

       https://man.openbsd.org/tmux.1#DESCRIPTION. Accessed April 1st, 2018.
    """

    server: "Server"

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
    def from_window_id(cls, server: "Server", window_id: str) -> "Window":
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
    def session(self) -> "Session":
        """Parent session of window."""
        assert isinstance(self.session_id, str)
        from libtmux.session import Session

        return Session.from_session_id(server=self.server, session_id=self.session_id)

    @property
    def panes(self) -> QueryList["Pane"]:
        """Panes contained by window.

        Can be accessed via
        :meth:`.panes.get() <libtmux._internal.query_list.QueryList.get()>` and
        :meth:`.panes.filter() <libtmux._internal.query_list.QueryList.filter()>`
        """
        panes: t.List[Pane] = [
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
        target: t.Optional[t.Union[str, int]] = None,
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

    def select_pane(self, target_pane: t.Union[str, int]) -> t.Optional["Pane"]:
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
        target: t.Optional[t.Union[int, str]] = None,
        start_directory: t.Optional[str] = None,
        attach: bool = False,
        direction: t.Optional[PaneDirection] = None,
        full_window_split: t.Optional[bool] = None,
        zoom: t.Optional[bool] = None,
        shell: t.Optional[str] = None,
        size: t.Optional[t.Union[str, int]] = None,
        environment: t.Optional[t.Dict[str, str]] = None,
    ) -> "Pane":
        """Split window on active pane and return the created :class:`Pane`.

        Parameters
        ----------
        attach : bool, optional
            make new window the current window after creating it, default
            True.
        start_directory : str, optional
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
            Environmental variables for new pane. tmux 3.0+ only. Passthrough to ``-e``.
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
        adjustment_direction: t.Optional[ResizeAdjustmentDirection] = None,
        adjustment: t.Optional[int] = None,
        # Manual
        height: t.Optional[int] = None,
        width: t.Optional[int] = None,
        # Expand / Shrink
        expand: t.Optional[bool] = None,
        shrink: t.Optional[bool] = None,
    ) -> "Window":
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
        if not has_gte_version("2.9"):
            warnings.warn("resize() requires tmux 2.9 or newer", stacklevel=2)
            return self

        tmux_args: t.Tuple[str, ...] = ()

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

    def last_pane(self) -> t.Optional["Pane"]:
        """Return last pane."""
        return self.select_pane("-l")

    def select_layout(self, layout: t.Optional[str] = None) -> "Window":
        """Select layout for window.

        Wrapper for ``$ tmux select-layout <layout>``.

        Parameters
        ----------
        layout : str, optional
            string of the layout, 'even-horizontal', 'tiled', etc. Entering
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
                custom dimensions (see :term:`tmux(1)` manpages).
        """
        cmd = ["select-layout"]

        if layout:  # tmux allows select-layout without args
            cmd.append(layout)

        proc = self.cmd(*cmd)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        return self

    def set_window_option(self, option: str, value: t.Union[int, str]) -> "Window":
        """Set option for tmux window.

        Wraps ``$ tmux set-window-option <option> <value>``.

        Parameters
        ----------
        option : str
            option to set, e.g. 'aggressive-resize'
        value : str
            window option value. True/False will turn in 'on' and 'off',
            also accepts string of 'on' or 'off' directly.

        Raises
        ------
        :exc:`exc.OptionError`, :exc:`exc.UnknownOption`,
        :exc:`exc.InvalidOption`, :exc:`exc.AmbiguousOption`
        """
        if isinstance(value, bool) and value:
            value = "on"
        elif isinstance(value, bool) and not value:
            value = "off"

        cmd = self.cmd(
            "set-window-option",
            option,
            value,
        )

        if isinstance(cmd.stderr, list) and len(cmd.stderr):
            handle_option_error(cmd.stderr[0])

        return self

    def show_window_options(self, g: t.Optional[bool] = False) -> "WindowOptionDict":
        """Return dict of options for window.

        .. versionchanged:: 0.13.0

           ``option`` removed, use show_window_option to return an individual option.

        Parameters
        ----------
        g : str, optional
            Pass ``-g`` flag for global variable, default False.
        """
        tmux_args: t.Tuple[str, ...] = ()

        if g:
            tmux_args += ("-g",)

        tmux_args += ("show-window-options",)
        cmd = self.cmd(*tmux_args)

        output = cmd.stdout

        # The shlex.split function splits the args at spaces, while also
        # retaining quoted sub-strings.
        #   shlex.split('this is "a test"') => ['this', 'is', 'a test']

        window_options: WindowOptionDict = {}
        for item in output:
            try:
                key, val = shlex.split(item)
            except ValueError:
                logger.exception(f"Error extracting option: {item}")
            assert isinstance(key, str)
            assert isinstance(val, str)

            if isinstance(val, str) and val.isdigit():
                window_options[key] = int(val)

        return window_options

    def show_window_option(
        self,
        option: str,
        g: bool = False,
    ) -> t.Optional[t.Union[str, int]]:
        """Return option value for the target window.

        todo: test and return True/False for on/off string

        Parameters
        ----------
        option : str
        g : bool, optional
            Pass ``-g`` flag, global. Default False.

        Raises
        ------
        :exc:`exc.OptionError`, :exc:`exc.UnknownOption`,
        :exc:`exc.InvalidOption`, :exc:`exc.AmbiguousOption`
        """
        tmux_args: t.Tuple[t.Union[str, int], ...] = ()

        if g:
            tmux_args += ("-g",)

        tmux_args += (option,)

        cmd = self.cmd("show-window-options", *tmux_args)

        if len(cmd.stderr):
            handle_option_error(cmd.stderr[0])

        window_options_output = cmd.stdout

        if not len(window_options_output):
            return None

        value_raw = next(shlex.split(item) for item in window_options_output)

        value: t.Union[str, int] = (
            int(value_raw[1]) if value_raw[1].isdigit() else value_raw[1]
        )

        return value

    def rename_window(self, new_name: str) -> "Window":
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

    def kill(
        self,
        all_except: t.Optional[bool] = None,
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
        flags: t.Tuple[str, ...] = ()

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
        session: t.Optional[str] = None,
    ) -> "Window":
        """Move current :class:`Window` object ``$ tmux move-window``.

        Parameters
        ----------
        destination : str, optional
            the ``target window`` or index to move the window to, default:
            empty string
        session : str, optional
            the ``target session`` or index to move the window to, default:
            current session.
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
        window_name: t.Optional[str] = None,
        *,
        start_directory: None = None,
        attach: bool = False,
        window_index: str = "",
        window_shell: t.Optional[str] = None,
        environment: t.Optional[t.Dict[str, str]] = None,
        direction: t.Optional[WindowDirection] = None,
    ) -> "Window":
        """Create new window respective of current window's position.

        See Also
        --------
        :meth:`Session.new_window()`

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
    def select(self) -> "Window":
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
    def active_pane(self) -> t.Optional["Pane"]:
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
            + f"{self.window_index}:{self.window_name}, {self.session})"
        )

    #
    # Aliases
    #
    @property
    def id(self) -> t.Optional[str]:
        """Alias of :attr:`Window.window_id`.

        >>> window.id
        '@1'

        >>> window.id == window.window_id
        True
        """
        return self.window_id

    @property
    def name(self) -> t.Optional[str]:
        """Alias of :attr:`Window.window_name`.

        >>> window.name
        '...'

        >>> window.name == window.window_name
        True
        """
        return self.window_name

    @property
    def index(self) -> t.Optional[str]:
        """Alias of :attr:`Window.window_index`.

        >>> window.index
        '1'

        >>> window.index == window.window_index
        True
        """
        return self.window_index

    @property
    def height(self) -> t.Optional[str]:
        """Alias of :attr:`Window.window_height`.

        >>> window.height.isdigit()
        True

        >>> window.height == window.window_height
        True
        """
        return self.window_height

    @property
    def width(self) -> t.Optional[str]:
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
        target: t.Optional[t.Union[int, str]] = None,
        start_directory: t.Optional[str] = None,
        attach: bool = False,
        vertical: bool = True,
        shell: t.Optional[str] = None,
        size: t.Optional[t.Union[str, int]] = None,
        percent: t.Optional[int] = None,  # deprecated
        environment: t.Optional[t.Dict[str, str]] = None,
    ) -> "Pane":
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
        warnings.warn(
            "Window.split_window() is deprecated in favor of Window.split()",
            category=DeprecationWarning,
            stacklevel=2,
        )

        if percent is not None:
            # Deprecated in 3.1 in favor of -l
            warnings.warn(
                f'Deprecated in favor of size="{str(percent).rstrip("%")}%" '
                + ' ("-l" flag) in tmux 3.1+.',
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
    def attached_pane(self) -> t.Optional["Pane"]:
        """Return attached :class:`Pane`.

        Notes
        -----
        .. deprecated:: 0.31

           Deprecated in favor of :meth:`.active_pane`.
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

    def select_window(self) -> "Window":
        """Select window.

        Notes
        -----
        .. deprecated:: 0.30

           Deprecated in favor of :meth:`.select()`.
        """
        warnings.warn(
            "Window.select_window() is deprecated in favor of Window.select()",
            category=DeprecationWarning,
            stacklevel=2,
        )
        assert isinstance(self.window_index, str)
        return self.session.select_window(self.window_index)

    def kill_window(self) -> None:
        """Kill the current :class:`Window` object. ``$ tmux kill-window``.

        Notes
        -----
        .. deprecated:: 0.30

           Deprecated in favor of :meth:`.kill()`.
        """
        warnings.warn(
            "Window.kill_server() is deprecated in favor of Window.kill()",
            category=DeprecationWarning,
            stacklevel=2,
        )
        proc = self.cmd("kill-window")

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def get(self, key: str, default: t.Optional[t.Any] = None) -> t.Any:
        """Return key-based lookup. Deprecated by attributes.

        .. deprecated:: 0.16

           Deprecated by attribute lookup.e.g. ``window['window_name']`` is now
           accessed via ``window.window_name``.

        """
        warnings.warn(
            "Window.get() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> t.Any:
        """Return item lookup by key. Deprecated in favor of attributes.

        .. deprecated:: 0.16

           Deprecated in favor of attributes. e.g. ``window['window_name']`` is now
           accessed via ``window.window_name``.

        """
        warnings.warn(
            f"Item lookups, e.g. window['{key}'] is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return getattr(self, key)

    def get_by_id(self, pane_id: str) -> t.Optional[Pane]:
        """Return pane by id. Deprecated in favor of :meth:`.panes.get()`.

        .. deprecated:: 0.16

           Deprecated by :meth:`.panes.get()`.

        """
        warnings.warn(
            "Window.get_by_id() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.panes.get(pane_id=pane_id, default=None)

    def where(self, kwargs: t.Dict[str, t.Any]) -> t.List[Pane]:
        """Filter through panes, return list of :class:`Pane`.

        .. deprecated:: 0.16

           Deprecated by :meth:`.panes.filter()`.

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

    def find_where(self, kwargs: t.Dict[str, t.Any]) -> t.Optional[Pane]:
        """Filter through panes, return first :class:`Pane`.

        .. deprecated:: 0.16

           Slated to be removed in favor of :meth:`.panes.get()`.

        """
        warnings.warn(
            "Window.find_where() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.panes.get(default=None, **kwargs)

    def _list_panes(self) -> t.List[PaneDict]:
        """Return list of panes (deprecated in favor of :meth:`.panes`).

        .. deprecated:: 0.16

           Slated to be removed in favor of :attr:`.panes`.

        """
        warnings.warn(
            "Window._list_panes() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return [pane.__dict__ for pane in self.panes]

    @property
    def _panes(self) -> t.List[PaneDict]:
        """Property / alias to return :meth:`~._list_panes`.

        .. deprecated:: 0.16

           Slated to be removed in favor of :attr:`.panes`.

        """
        warnings.warn("_panes is deprecated", category=DeprecationWarning, stacklevel=2)
        return self._list_panes()

    def list_panes(self) -> t.List["Pane"]:
        """Return list of :class:`Pane` for the window.

        .. deprecated:: 0.16

           Slated to be removed in favor of :attr:`.panes`.

        """
        warnings.warn(
            "list_panes() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.panes

    @property
    def children(self) -> QueryList["Pane"]:
        """Was used by TmuxRelationalObject (but that's longer used in this class).

        .. deprecated:: 0.16

           Slated to be removed in favor of :attr:`.panes`.

        """
        warnings.warn(
            "Server.children is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.panes
