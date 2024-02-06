"""Pythonization of the :term:`tmux(1)` session.

libtmux.session
~~~~~~~~~~~~~~~

"""
import dataclasses
import logging
import pathlib
import typing as t
import warnings

from libtmux._internal.query_list import QueryList
from libtmux.common import tmux_cmd
from libtmux.formats import FORMAT_SEPARATOR
from libtmux.neo import Obj, fetch_obj, fetch_objs
from libtmux.pane import Pane
from libtmux.window import Window

from . import exc
from .common import (
    EnvironmentMixin,
    WindowDict,
    handle_option_error,
    has_gte_version,
    has_version,
    session_check_name,
)

if t.TYPE_CHECKING:
    from .server import Server


logger = logging.getLogger(__name__)


@dataclasses.dataclass()
class Session(Obj, EnvironmentMixin):
    """:term:`tmux(1)` :term:`Session` [session_manual]_.

    Holds :class:`Window` objects.

    Parameters
    ----------
    server : :class:`Server`

    Examples
    --------
    >>> session
    Session($1 ...)

    >>> session.windows
    [Window(@1 ...:..., Session($1 ...)]

    >>> session.attached_window
    Window(@1 ...:..., Session($1 ...)

    >>> session.attached_pane
    Pane(%1 Window(@1 ...:..., Session($1 ...)))

    References
    ----------
    .. [session_manual] tmux session. openbsd manpage for TMUX(1).
           "When tmux is started it creates a new session with a single window
           and displays it on screen..."

           "A session is a single collection of pseudo terminals under the
           management of tmux.  Each session has one or more windows linked to
           it."

       https://man.openbsd.org/tmux.1#DESCRIPTION. Accessed April 1st, 2018.
    """

    server: "Server"

    def refresh(self) -> None:
        """Refresh session attributes from tmux."""
        assert isinstance(self.session_id, str)
        return super()._refresh(
            obj_key="session_id",
            obj_id=self.session_id,
            list_cmd="list-sessions",
        )

    @classmethod
    def from_session_id(cls, server: "Server", session_id: str) -> "Session":
        """Create Session from existing session_id."""
        session = fetch_obj(
            obj_key="session_id",
            obj_id=session_id,
            list_cmd="list-sessions",
            server=server,
        )
        return cls(server=server, **session)

    #
    # Relations
    #
    @property
    def windows(self) -> QueryList["Window"]:  # type:ignore
        """Windows contained by session.

        Can be accessed via
        :meth:`.windows.get() <libtmux._internal.query_list.QueryList.get()>` and
        :meth:`.windows.filter() <libtmux._internal.query_list.QueryList.filter()>`
        """
        windows: t.List["Window"] = [
            Window(server=self.server, **obj)
            for obj in fetch_objs(
                list_cmd="list-windows",
                list_extra_args=["-t", str(self.session_id)],
                server=self.server,
            )
            if obj.get("session_id") == self.session_id
        ]

        return QueryList(windows)

    @property
    def panes(self) -> QueryList["Pane"]:  # type:ignore
        """Panes contained by session's windows.

        Can be accessed via
        :meth:`.panes.get() <libtmux._internal.query_list.QueryList.get()>` and
        :meth:`.panes.filter() <libtmux._internal.query_list.QueryList.filter()>`
        """
        panes: t.List["Pane"] = [
            Pane(server=self.server, **obj)
            for obj in fetch_objs(
                list_cmd="list-panes",
                list_extra_args=["-s", "-t", str(self.session_id)],
                server=self.server,
            )
            if obj.get("session_id") == self.session_id
        ]

        return QueryList(panes)

    #
    # Command
    #
    def cmd(self, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        """Execute tmux subcommand against target session. See :meth:`server.cmd`.

        Returns
        -------
        :class:`server.cmd`

        Notes
        -----
        .. versionchanged:: 0.8

            Renamed from ``.tmux`` to ``.cmd``.
        """
        # if -t is not set in any arg yet
        if not any("-t" in str(x) for x in args):
            # insert -t immediately after 1st arg, as per tmux format
            new_args: t.Tuple[str, ...] = ()
            new_args += (args[0],)
            assert isinstance(self.session_id, str)
            new_args += (
                "-t",
                self.session_id,
            )
            new_args += tuple(args[1:])
            args = new_args
        return self.server.cmd(*args, **kwargs)

    """
    Commands (tmux-like)
    """

    def set_option(
        self,
        option: str,
        value: t.Union[str, int],
        _global: bool = False,
    ) -> "Session":
        """Set option ``$ tmux set-option <option> <value>``.

        Parameters
        ----------
        option : str
            the window option. such as 'default-shell'.
        value : str, int, or bool
            True/False will turn in 'on' and 'off'. You can also enter 'on' or
            'off' directly.
        _global : bool, optional
            check for option globally across all servers (-g)

        Raises
        ------
        :exc:`exc.OptionError`, :exc:`exc.UnknownOption`,
        :exc:`exc.InvalidOption`, :exc:`exc.AmbiguousOption`

        Notes
        -----
        .. todo::

            Needs tests
        """
        if isinstance(value, bool) and value:
            value = "on"
        elif isinstance(value, bool) and not value:
            value = "off"

        tmux_args: t.Tuple[t.Union[str, int], ...] = ()

        if _global:
            tmux_args += ("-g",)

        assert isinstance(option, str)
        assert isinstance(value, (str, int))

        tmux_args += (
            option,
            value,
        )

        proc = self.cmd("set-option", *tmux_args)

        if isinstance(proc.stderr, list) and len(proc.stderr):
            handle_option_error(proc.stderr[0])

        return self

    def show_options(
        self,
        _global: t.Optional[bool] = False,
    ) -> t.Dict[str, t.Union[str, int]]:
        """Return dict of options for the session.

        Parameters
        ----------
        _global : bool, optional
            Pass ``-g`` flag for global variable (server-wide)

        Returns
        -------
        :py:obj:`dict`

        Notes
        -----
        Uses ``_global`` for keyword name instead of ``global`` to avoid
        colliding with reserved keyword.
        """
        tmux_args: t.Tuple[str, ...] = ()

        if _global:
            tmux_args += ("-g",)

        tmux_args += ("show-options",)
        session_output = self.cmd(*tmux_args).stdout

        session_options: t.Dict[str, t.Union[str, int]] = {}
        for item in session_output:
            key, val = item.split(" ", maxsplit=1)
            assert isinstance(key, str)
            assert isinstance(val, str)

            if isinstance(val, str) and val.isdigit():
                session_options[key] = int(val)

        return session_options

    def show_option(
        self,
        option: str,
        _global: bool = False,
    ) -> t.Optional[t.Union[str, int, bool]]:
        """Return option value for the target session.

        Parameters
        ----------
        option : str
            option name
        _global : bool, optional
            use global option scope, same as ``-g``

        Returns
        -------
        str, int, or bool

        Raises
        ------
        :exc:`exc.OptionError`, :exc:`exc.UnknownOption`,
        :exc:`exc.InvalidOption`, :exc:`exc.AmbiguousOption`

        Notes
        -----
        Uses ``_global`` for keyword name instead of ``global`` to avoid
        colliding with reserved keyword.

        Test and return True/False for on/off string.
        """
        tmux_args: t.Tuple[str, ...] = ()

        if _global:
            tmux_args += ("-g",)

        tmux_args += (option,)

        cmd = self.cmd("show-options", *tmux_args)

        if isinstance(cmd.stderr, list) and len(cmd.stderr):
            handle_option_error(cmd.stderr[0])

        if not len(cmd.stdout):
            return None

        value_raw: t.List[str] = next(item.split(" ") for item in cmd.stdout)

        assert isinstance(value_raw[0], str)
        assert isinstance(value_raw[1], str)

        value: t.Union[str, int] = (
            int(value_raw[1]) if value_raw[1].isdigit() else value_raw[1]
        )

        return value

    def select_window(self, target_window: t.Union[str, int]) -> "Window":
        """Select window, return selected window.

        Parameters
        ----------
        window : str
            ``target_window`` also 'last-window' (``-l``), 'next-window'
            (``-n``), or 'previous-window' (``-p``)

        Returns
        -------
        :class:`Window`

        Notes
        -----
        .. todo::

            assure ``-l``, ``-n``, ``-p`` work.
        """
        # Note that we also provide the session ID here, since cmd()
        # will not automatically add it as there is already a '-t'
        # argument provided.
        target = f"-t{self.session_id}:{target_window}"

        proc = self.cmd("select-window", target)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        return self.attached_window

    #
    # Computed properties
    #
    @property
    def attached_window(self) -> "Window":
        """Return active :class:`Window` object."""
        active_windows = [
            window for window in self.windows if window.window_active == "1"
        ]

        if len(active_windows) == 1:
            return next(iter(active_windows))
        elif len(active_windows) == 0:
            raise exc.NoActiveWindow()
        else:
            raise exc.MultipleActiveWindows(count=len(active_windows))

        if len(self._windows) == 0:
            raise exc.NoWindowsExist()

    def attach_session(self) -> "Session":
        """Return ``$ tmux attach-session`` aka alias: ``$ tmux attach``."""
        proc = self.cmd("attach-session", "-t%s" % self.session_id)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        return self

    def kill_session(self) -> None:
        """Destroy session."""
        proc = self.cmd("kill-session", "-t%s" % self.session_id)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def switch_client(self) -> "Session":
        """Switch client to session.

        Raises
        ------
        :exc:`exc.LibTmuxException`
        """
        proc = self.cmd("switch-client", "-t%s" % self.session_id)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        return self

    def rename_session(self, new_name: str) -> "Session":
        """Rename session and return new :class:`Session` object.

        Parameters
        ----------
        new_name : str
            new session name

        Raises
        ------
        :exc:`exc.BadSessionName`
        """
        session_check_name(new_name)

        proc = self.cmd("rename-session", new_name)

        if proc.stderr:
            if has_version("2.7") and "no current client" in proc.stderr:
                """tmux 2.7 raises "no current client" warning on BSD systems.

                Should be fixed next release:

                - https://www.mail-archive.com/tech@openbsd.org/msg45186.html
                - https://marc.info/?l=openbsd-cvs&m=152183263526828&w=2
                """
            else:
                raise exc.LibTmuxException(proc.stderr)

        self.refresh()

        return self

    def new_window(
        self,
        window_name: t.Optional[str] = None,
        start_directory: None = None,
        attach: bool = True,
        window_index: str = "",
        window_shell: t.Optional[str] = None,
        environment: t.Optional[t.Dict[str, str]] = None,
    ) -> "Window":
        """Create new window, returns new :class:`Window`.

        By default, this will make the window active. For the new window
        to be created and not set to current, pass in ``attach=False``.

        Parameters
        ----------
        window_name : str, optional
        start_directory : str, optional
            working directory in which the new window is created.
        attach : bool, optional
            make new window the current window after creating it, default True.
        window_index : str
            create the new window at the given index position. Default is empty
            string which will create the window in the next available position.
        window_shell : str, optional
            execute a command on starting the window.  The window will close
            when the command exits.

            .. note::
                When this command exits the window will close.  This feature is
                useful for long-running processes where the closing of the
                window upon completion is desired.

        Returns
        -------
        :class:`Window`
        """
        window_args: t.Tuple[str, ...] = ()

        if not attach:
            window_args += ("-d",)

        window_args += ("-P",)

        if start_directory:
            # as of 2014-02-08 tmux 1.9-dev doesn't expand ~ in new-window -c.
            start_directory = pathlib.Path(start_directory).expanduser()
            window_args += (f"-c{start_directory}",)

        window_args += ("-F#{window_id}",)  # output
        if window_name is not None and isinstance(window_name, str):
            window_args += ("-n", window_name)

        window_args += (
            # empty string for window_index will use the first one available
            f"-t{self.session_id}:{window_index}",
        )

        if environment:
            if has_gte_version("3.0"):
                for k, v in environment.items():
                    window_args += (f"-e{k}={v}",)
            else:
                logger.warning(
                    "Cannot set up environment as tmux 3.0 or newer is required.",
                )

        if window_shell:
            window_args += (window_shell,)

        cmd = self.cmd("new-window", *window_args)

        if cmd.stderr:
            raise exc.LibTmuxException(cmd.stderr)

        window_output = cmd.stdout[0]

        window_formatters = dict(
            zip(["window_id"], window_output.split(FORMAT_SEPARATOR)),
        )

        return Window.from_window_id(
            server=self.server,
            window_id=window_formatters["window_id"],
        )

    def kill_window(self, target_window: t.Optional[str] = None) -> None:
        """Close a tmux window, and all panes inside it, ``$ tmux kill-window``.

        Kill the current window or the window at ``target-window``. removing it
        from any sessions to which it is linked.

        Parameters
        ----------
        target_window : str, optional
            window to kill
        """
        if target_window:
            if isinstance(target_window, int):
                target = "-t%s:%d" % (self.window_name, target_window)
            else:
                target = "-t%s" % target_window

        proc = self.cmd("kill-window", target)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    #
    # Computed properties
    #
    @property
    def attached_pane(self) -> t.Optional["Pane"]:
        """Return active :class:`Pane` object."""
        return self.attached_window.attached_pane

    #
    # Dunder
    #
    def __eq__(self, other: object) -> bool:
        """Equal operator for :class:`Session` object."""
        if isinstance(other, Session):
            return self.session_id == other.session_id
        return False

    def __repr__(self) -> str:
        """Representation of :class:`Session` object."""
        return f"{self.__class__.__name__}({self.session_id} {self.session_name})"

    #
    # Aliases
    #
    @property
    def id(self) -> t.Optional[str]:
        """Alias of :attr:`Session.session_id`.

        >>> session.id
        '$1'

        >>> session.id == session.session_id
        True
        """
        return self.session_id

    @property
    def name(self) -> t.Optional[str]:
        """Alias of :attr:`Session.session_name`.

        >>> session.name
        'libtmux_...'

        >>> session.name == session.session_name
        True
        """
        return self.session_name

    #
    # Legacy: Redundant stuff we want to remove
    #
    def get(self, key: str, default: t.Optional[t.Any] = None) -> t.Any:
        """Return key-based lookup. Deprecated by attributes.

        .. deprecated:: 0.16

           Deprecated by attribute lookup.e.g. ``session['session_name']`` is now
           accessed via ``session.session_name``.

        """
        warnings.warn("Session.get() is deprecated", stacklevel=2)
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> t.Any:
        """Return item lookup by key. Deprecated in favor of attributes.

        .. deprecated:: 0.16

           Deprecated in favor of attributes. e.g. ``session['session_name']`` is now
           accessed via ``session.session_name``.

        """
        warnings.warn(
            f"Item lookups, e.g. session['{key}'] is deprecated",
            stacklevel=2,
        )
        return getattr(self, key)

    def get_by_id(self, session_id: str) -> t.Optional[Window]:
        """Return window by id. Deprecated in favor of :meth:`.windows.get()`.

        .. deprecated:: 0.16

           Deprecated by :meth:`.windows.get()`.

        """
        warnings.warn("Session.get_by_id() is deprecated", stacklevel=2)
        return self.windows.get(window_id=session_id, default=None)

    def where(self, kwargs: t.Dict[str, t.Any]) -> t.List[Window]:
        """Filter through windows, return list of :class:`Window`.

        .. deprecated:: 0.16

           Deprecated by :meth:`.windows.filter()`.

        """
        warnings.warn("Session.where() is deprecated", stacklevel=2)
        try:
            return self.windows.filter(**kwargs)
        except IndexError:
            return []

    def find_where(self, kwargs: t.Dict[str, t.Any]) -> t.Optional[Window]:
        """Filter through windows, return first :class:`Window`.

        .. deprecated:: 0.16

           Slated to be removed in favor of :meth:`.windows.get()`.

        """
        warnings.warn("Session.find_where() is deprecated", stacklevel=2)
        return self.windows.get(default=None, **kwargs)

    def _list_windows(self) -> t.List["WindowDict"]:
        """Return list of windows (deprecated in favor of :attr:`.windows`).

        .. deprecated:: 0.16

           Slated to be removed in favor of :attr:`.windows`.

        """
        warnings.warn("Session._list_windows() is deprecated", stacklevel=2)
        return [w.__dict__ for w in self.windows]

    @property
    def _windows(self) -> t.List["WindowDict"]:
        """Property / alias to return :meth:`Session._list_windows`.

        .. deprecated:: 0.16

           Slated to be removed in favor of :attr:`.windows`.

        """
        warnings.warn("Session._windows is deprecated", stacklevel=2)
        return self._list_windows()

    def list_windows(self) -> t.List["Window"]:
        """Return a list of :class:`Window` from the ``tmux(1)`` session.

        .. deprecated:: 0.16

           Slated to be removed in favor of :attr:`.windows`.

        """
        warnings.warn("Session.list_windows() is deprecated", stacklevel=2)
        return self.windows

    @property
    def children(self) -> QueryList["Window"]:  # type:ignore
        """Was used by TmuxRelationalObject (but that's longer used in this class).

        .. deprecated:: 0.16

           Slated to be removed in favor of :attr:`.windows`.

        """
        warnings.warn("Session.children is deprecated", stacklevel=2)
        return self.windows
