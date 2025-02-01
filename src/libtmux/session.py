"""Provide a Pythonic representation of the :term:`tmux(1)` session.

This module implements the :class:`Session` class, representing a tmux session
capable of containing multiple windows and panes. It includes methods for
attaching, killing, renaming, or modifying the session, as well as property
accessors for session attributes.

libtmux.session
~~~~~~~~~~~~~~~
"""

from __future__ import annotations

import dataclasses
import logging
import pathlib
import typing as t
import warnings

from libtmux._internal.query_list import QueryList
from libtmux.constants import WINDOW_DIRECTION_FLAG_MAP, WindowDirection
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
    import sys
    import types

    from libtmux.common import tmux_cmd

    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing_extensions import Self

    from .server import Server


logger = logging.getLogger(__name__)


@dataclasses.dataclass()
class Session(Obj, EnvironmentMixin):
    """Represent a :term:`tmux(1)` session [session_manual]_.

    Holds :class:`Window` objects.

    Parameters
    ----------
    server
        The :class:`Server` instance that owns this session.

    Examples
    --------
    >>> session
    Session($1 ...)

    >>> session.windows
    [Window(@1 ...:..., Session($1 ...)]

    >>> session.active_window
    Window(@1 ...:..., Session($1 ...))

    >>> session.active_pane
    Pane(%1 Window(@1 ...:..., Session($1 ...)))

    The session can be used as a context manager to ensure proper cleanup:

    >>> with server.new_session() as session:
    ...     window = session.new_window()
    ...     # Do work with the window
    ...     # Session will be killed automatically when exiting the context

    References
    ----------
    .. [session_manual] tmux session. openbsd manpage for TMUX(1).
           "When tmux is started it creates a new session with a single window
           and displays it on screen..."

           "A session is a single collection of pseudo terminals under the
           management of tmux.  Each session has one or more windows linked
           to it."

       https://man.openbsd.org/tmux.1#DESCRIPTION. Accessed April 1st, 2018.
    """

    server: Server

    def __enter__(self) -> Self:
        """Enter the context, returning self.

        Returns
        -------
        :class:`Session`
            The session instance
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Exit the context, killing the session if it exists.

        Parameters
        ----------
        exc_type : type[BaseException] | None
            The type of the exception that was raised
        exc_value : BaseException | None
            The instance of the exception that was raised
        exc_tb : types.TracebackType | None
            The traceback of the exception that was raised
        """
        if self.session_name is not None and self.server.has_session(self.session_name):
            self.kill()

    def refresh(self) -> None:
        """Refresh session attributes from tmux."""
        assert isinstance(self.session_id, str)
        return super()._refresh(
            obj_key="session_id",
            obj_id=self.session_id,
            list_cmd="list-sessions",
        )

    @classmethod
    def from_session_id(cls, server: Server, session_id: str) -> Session:
        """Create a :class:`Session` from an existing session_id."""
        session = fetch_obj(
            obj_key="session_id",
            obj_id=session_id,
            list_cmd="list-sessions",
            server=server,
        )
        return cls(server=server, **session)

    @property
    def windows(self) -> QueryList[Window]:
        """Return a :class:`QueryList` of :class:`Window` objects in this session.

        Can be accessed via
        :meth:`.windows.get() <libtmux._internal.query_list.QueryList.get()>` and
        :meth:`.windows.filter() <libtmux._internal.query_list.QueryList.filter()>`
        """
        windows: list[Window] = [
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
    def panes(self) -> QueryList[Pane]:
        """Return a :class:`QueryList` of :class:`Pane` for all windows of this session.

        Can be accessed via
        :meth:`.panes.get() <libtmux._internal.query_list.QueryList.get()>` and
        :meth:`.panes.filter() <libtmux._internal.query_list.QueryList.filter()>`
        """
        panes: list[Pane] = [
            Pane(server=self.server, **obj)
            for obj in fetch_objs(
                list_cmd="list-panes",
                list_extra_args=["-s", "-t", str(self.session_id)],
                server=self.server,
            )
            if obj.get("session_id") == self.session_id
        ]
        return QueryList(panes)

    def cmd(
        self,
        cmd: str,
        *args: t.Any,
        target: str | int | None = None,
    ) -> tmux_cmd:
        """Execute a tmux subcommand within the context of this session.

        Automatically binds ``-t <session_id>`` to the command unless
        overridden by the `target` parameter.

        Parameters
        ----------
        cmd
            The tmux subcommand to execute.
        *args
            Additional arguments for the tmux command.
        target, optional
            Custom target override. By default, the target is this session's ID.

        Examples
        --------
        >>> session.cmd('new-window', '-P').stdout[0]
        'libtmux...:....0'

        From raw output to a `Window` object:

        >>> Window.from_window_id(
        ...     window_id=session.cmd('new-window', '-P', '-F#{window_id}').stdout[0],
        ...     server=session.server
        ... )
        Window(@... ...:..., Session($1 libtmux_...))

        Returns
        -------
        tmux_cmd
            The result of the tmux command execution.

        Notes
        -----
        .. versionchanged:: 0.34
           Passing target by ``-t`` is ignored. Use the ``target`` parameter instead.

        .. versionchanged:: 0.8
           Renamed from ``.tmux`` to ``.cmd``.
        """
        if target is None:
            target = self.session_id
        return self.server.cmd(cmd, *args, target=target)

    def set_option(
        self,
        option: str,
        value: str | int,
        global_: bool = False,
    ) -> Session:
        """Set a tmux session option (``$ tmux set-option <option> <value>``).

        Parameters
        ----------
        option
            The session option (e.g. 'default-shell').
        value
            Option value. A bool `True` becomes 'on'; `False` becomes 'off'.
        global_, optional
            If True, set the option globally for the server (``-g``).

        Returns
        -------
        Session
            This :class:`Session` (for chaining).

        Raises
        ------
        exc.OptionError
        exc.UnknownOption
        exc.InvalidOption
        exc.AmbiguousOption
        """
        if isinstance(value, bool):
            value = "on" if value else "off"

        tmux_args: tuple[str | int, ...] = ()
        if global_:
            tmux_args += ("-g",)
        tmux_args += (option, value)

        proc = self.cmd("set-option", *tmux_args)
        if isinstance(proc.stderr, list) and proc.stderr:
            handle_option_error(proc.stderr[0])

        return self

    def show_options(
        self,
        global_: bool | None = False,
    ) -> dict[str, str | int]:
        """Return a dictionary of session options.

        Parameters
        ----------
        global_, optional
            If True, retrieve global session options (``-g``).

        Returns
        -------
        dict of str to str or int
            Dictionary of session options.
        """
        tmux_args: tuple[str, ...] = ()
        if global_:
            tmux_args += ("-g",)
        tmux_args += ("show-options",)

        session_output = self.cmd(*tmux_args).stdout
        session_options: dict[str, str | int] = {}

        for item in session_output:
            key, val = item.split(" ", maxsplit=1)
            if val.isdigit():
                session_options[key] = int(val)
            else:
                session_options[key] = val

        return session_options

    def show_option(
        self,
        option: str,
        global_: bool = False,
    ) -> str | int | bool | None:
        """Return the value of a specific session option.

        Parameters
        ----------
        option
            Name of the session option to retrieve.
        global_, optional
            If True, retrieve the global session option (``-g``).

        Returns
        -------
        str, int, bool, or None
            The value of the requested option. Returns None if no output.

        Raises
        ------
        exc.OptionError
        exc.UnknownOption
        exc.InvalidOption
        exc.AmbiguousOption
        """
        tmux_args: tuple[str, ...] = ()
        if global_:
            tmux_args += ("-g",)
        tmux_args += (option,)

        cmd_result = self.cmd("show-options", *tmux_args)
        if isinstance(cmd_result.stderr, list) and cmd_result.stderr:
            handle_option_error(cmd_result.stderr[0])

        if not cmd_result.stdout:
            return None

        value_raw = next(item.split(" ") for item in cmd_result.stdout)
        if value_raw[1].isdigit():
            return int(value_raw[1])
        return value_raw[1]

    def select_window(self, target_window: str | int) -> Window:
        """Select a window in this session, return the newly selected :class:`Window`.

        Parameters
        ----------
        target_window
            The window index or special parameter (e.g., 'last-window' via `-l`).

        Returns
        -------
        Window
            The now-active window after selection.

        Raises
        ------
        exc.LibTmuxException
            If tmux reports an error (see stderr).

        Notes
        -----
        This method attempts to format the target as ``<session_id>:<window_id>``.
        """
        target = f"{self.session_id}:{target_window}"
        proc = self.cmd("select-window", target=target)
        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)
        return self.active_window

    @property
    def active_pane(self) -> Pane | None:
        """Return the active :class:`Pane` for the active window of this session."""
        return self.active_window.active_pane

    @property
    def active_window(self) -> Window:
        """Return the active :class:`Window` in this session.

        Raises
        ------
        exc.NoActiveWindow
            If no windows are present in the session.
        exc.MultipleActiveWindows
            If more than one window is found to be active, which should not happen
            under normal circumstances.
        """
        active_windows = self.windows.filter(window_active="1")
        if len(active_windows) == 1:
            return next(iter(active_windows))
        if len(active_windows) == 0:
            raise exc.NoActiveWindow
        raise exc.MultipleActiveWindows(count=len(active_windows))

        # Unreachable, but kept for compatibility if the code changes in the future:
        # if len(self._windows) == 0:
        #     raise exc.NoWindowsExist
        # return None

    def attach(
        self,
        exit_: bool | None = None,
        flags_: list[str] | None = None,
    ) -> Session:
        """Attach to this session (``tmux attach-session``).

        Parameters
        ----------
        exit_, optional
            If True, pass the ``-x`` flag to exit the client after attaching.
        flags_, optional
            Additional flags to pass as a list (they will be joined by commas).

        Returns
        -------
        Session
            This :class:`Session` (for chaining).

        Raises
        ------
        exc.LibTmuxException
            If tmux reports an error (see stderr).

        Examples
        --------
        >>> session = server.new_session()
        >>> session not in server.attached_sessions
        True
        """
        flags: tuple[str, ...] = ()
        if exit_:
            flags += ("-x",)
        if flags_:
            flags += (",".join(flags_),)

        proc = self.cmd("attach-session", *flags)
        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)
        self.refresh()
        return self

    def kill(
        self,
        all_except: bool | None = None,
        clear: bool | None = None,
    ) -> None:
        """Kill this :class:`Session`, closing linked windows and detaching all clients.

        Wrapper for ``tmux kill-session``.

        Parameters
        ----------
        all_except, optional
            If True, kill all sessions except this one.
        clear, optional
            If True, clear alerts in all windows (bell, activity, or silence).

        Raises
        ------
        exc.LibTmuxException
            If tmux reports an error (see stderr).

        Examples
        --------
        Kill a session:

        >>> session_1 = server.new_session()
        >>> session_1 in server.sessions
        True
        >>> session_1.kill()
        >>> session_1 not in server.sessions
        True

        Kill all sessions except this one:

        >>> one_session_to_rule_them_all = server.new_session()
        >>> other_sessions = server.new_session(), server.new_session()
        >>> all([w in server.sessions for w in other_sessions])
        True
        >>> one_session_to_rule_them_all.kill(all_except=True)
        >>> all([w not in server.sessions for w in other_sessions])
        True
        >>> one_session_to_rule_them_all in server.sessions
        True
        """
        flags: tuple[str, ...] = ()
        if all_except:
            flags += ("-a",)
        if clear:
            flags += ("-C",)

        proc = self.cmd("kill-session", *flags)
        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def switch_client(self) -> Session:
        """Switch the attached client to this session (``tmux switch-client``).

        Returns
        -------
        Session
            This :class:`Session` (for chaining).

        Raises
        ------
        exc.LibTmuxException
            If tmux reports an error (see stderr).
        """
        proc = self.cmd("switch-client")
        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)
        return self

    def rename_session(self, new_name: str) -> Session:
        """Rename this session, returning the same :class:`Session` instance updated.

        Parameters
        ----------
        new_name
            New name for the session.

        Returns
        -------
        Session
            This :class:`Session` (for chaining).

        Raises
        ------
        exc.BadSessionName
            If `new_name` is invalid.
        exc.LibTmuxException
            If tmux reports an error (see stderr).
        """
        session_check_name(new_name)
        proc = self.cmd("rename-session", new_name)

        if proc.stderr:
            # For tmux 2.7: "no current client" warning on some systems
            if has_version("2.7") and "no current client" in proc.stderr:
                pass
            else:
                raise exc.LibTmuxException(proc.stderr)

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
        target_window: str | None = None,
    ) -> Window:
        """Create and return a new :class:`Window` in this session.

        By default, the new window becomes the active window.
        To create a new window without making it active, pass ``attach=False``.

        Parameters
        ----------
        window_name, optional
            Name of the new window.
        start_directory, optional
            Working directory in which the new window is created.
        attach, optional
            Whether to make the new window the active window. Default is False.
        window_index, optional
            Position (index) at which to create the new window.
        window_shell, optional
            Shell command to run in the new window. The window will close
            upon command completion if provided.
        environment, optional
            Dictionary of environment variables for the new window (tmux 3.0+).
        direction, optional
            Create the new window before or after the target window
            (tmux 3.2+ required).
        target_window, optional
            If provided by :meth:`Window.new_window()`, denotes a target window
            for placing the new window in relation to it (tmux 3.2+).

        Returns
        -------
        Window
            The newly created :class:`Window`.

        Examples
        --------
        .. ::
            >>> import pytest
            >>> from libtmux.common import has_lt_version
            >>> if has_lt_version('3.2'):
            ...     pytest.skip('direction doctests require tmux 3.2 or newer')
        >>> window_initial = session.new_window(window_name='Example')
        >>> window_initial
        Window(@... 2:Example, Session($1 libtmux_...))
        >>> window_initial.window_index
        '2'

        >>> window_before = session.new_window(
        ...     window_name='Window before', direction=WindowDirection.Before
        ... )
        >>> window_initial.refresh()
        >>> window_before
        Window(@... 1:Window before, Session($1 libtmux_...))
        >>> window_initial
        Window(@... 3:Example, Session($1 libtmux_...))

        >>> window_after = session.new_window(
        ...     window_name='Window after', direction=WindowDirection.After
        ... )
        >>> window_initial.refresh()
        >>> window_after.refresh()
        >>> window_after
        Window(@... 3:Window after, Session($1 libtmux_...))
        >>> window_initial
        Window(@... 4:Example, Session($1 libtmux_...))
        >>> window_before
        Window(@... 1:Window before, Session($1 libtmux_...))
        """
        window_args: tuple[str, ...] = ()

        if not attach:
            window_args += ("-d",)
        window_args += ("-P",)

        if start_directory:
            start_path = pathlib.Path(start_directory).expanduser()
            window_args += (f"-c{start_path}",)

        window_args += ("-F#{window_id}",)  # Output format

        if window_name is not None:
            window_args += ("-n", window_name)

        if environment:
            if has_gte_version("3.0"):
                for k, v in environment.items():
                    window_args += (f"-e{k}={v}",)
            else:
                logger.warning("Environment flag ignored, requires tmux 3.0 or newer.")

        if direction is not None:
            if has_gte_version("3.2"):
                window_args += (WINDOW_DIRECTION_FLAG_MAP[direction],)
            else:
                logger.warning("Direction flag ignored, requires tmux 3.2 or newer.")

        target: str | None = None
        if window_index is not None:
            target = f"{self.session_id}:{window_index}"
        if target_window:
            if has_gte_version("3.2"):
                target = target_window
            else:
                logger.warning("Window target ignored, requires tmux 3.2 or newer.")
        elif window_index is not None:
            window_args += (f"-t{self.session_id}:{window_index}",)

        if window_shell:
            window_args += (window_shell,)

        cmd_result = self.cmd("new-window", *window_args, target=target)
        if cmd_result.stderr:
            raise exc.LibTmuxException(cmd_result.stderr)

        window_output = cmd_result.stdout[0]
        window_formatters = dict(
            zip(["window_id"], window_output.split(FORMAT_SEPARATOR)),
        )

        return Window.from_window_id(
            server=self.server,
            window_id=window_formatters["window_id"],
        )

    def kill_window(self, target_window: str | None = None) -> None:
        """Kill a window (``$ tmux kill-window``) within this session.

        If `target_window` is provided, that window will be killed. If no
        target is specified, the currently active window will be killed.

        Parameters
        ----------
        target_window, optional
            The window index or ID to kill.

        Raises
        ------
        exc.LibTmuxException
            If tmux reports an error (see stderr).
        """
        target = None
        if target_window:
            target = f"{target_window}"

        proc = self.cmd("kill-window", target=target)
        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def __eq__(self, other: object) -> bool:
        """Compare two sessions by their ``session_id``."""
        if isinstance(other, Session):
            return self.session_id == other.session_id
        return False

    def __repr__(self) -> str:
        """Return a string representation of this :class:`Session`."""
        return f"{self.__class__.__name__}({self.session_id} {self.session_name})"

    @property
    def id(self) -> str | None:
        """Alias of :attr:`Session.session_id`.

        Examples
        --------
        >>> session.id
        '$1'

        >>> session.id == session.session_id
        True
        """
        return self.session_id

    @property
    def name(self) -> str | None:
        """Alias of :attr:`Session.session_name`.

        Examples
        --------
        >>> session.name
        'libtmux_...'

        >>> session.name == session.session_name
        True
        """
        return self.session_name

    # Deprecated / Legacy Methods

    @property
    def attached_pane(self) -> Pane | None:
        """Return the active :class:`Pane` (deprecated).

        .. deprecated:: 0.31
           Use :meth:`.active_pane`.
        """
        warnings.warn(
            "Session.attached_pane() is deprecated in favor of Session.active_pane()",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.active_window.active_pane

    @property
    def attached_window(self) -> Window:
        """Return the active :class:`Window` (deprecated).

        .. deprecated:: 0.31
           Use :meth:`.active_window`.
        """
        warnings.warn(
            (
                "Session.attached_window() is deprecated in favor of "
                + "Session.active_window()"
            ),
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.active_window

    def attach_session(self) -> Session:
        """Attach to the session (deprecated).

        .. deprecated:: 0.30
           Use :meth:`.attach()`.
        """
        warnings.warn(
            "Session.attach_session() is deprecated in favor of Session.attach()",
            category=DeprecationWarning,
            stacklevel=2,
        )
        proc = self.cmd("attach-session")
        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)
        return self

    def kill_session(self) -> None:
        """Kill this session (deprecated).

        .. deprecated:: 0.30
           Use :meth:`.kill()`.
        """
        warnings.warn(
            "Session.kill_session() is deprecated in favor of Session.kill()",
            category=DeprecationWarning,
            stacklevel=2,
        )
        proc = self.cmd("kill-session")
        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def get(self, key: str, default: t.Any | None = None) -> t.Any:
        """Return a value by key lookup (deprecated).

        .. deprecated:: 0.16
           Use attribute lookup, e.g. ``session.session_name``.
        """
        warnings.warn(
            "Session.get() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> t.Any:
        """Return a value by item lookup (deprecated).

        .. deprecated:: 0.16
           Use attribute lookup, e.g. ``session.session_name``.
        """
        warnings.warn(
            f"Item lookups, e.g. session['{key}'] is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return getattr(self, key)

    def get_by_id(self, session_id: str) -> Window | None:
        """Return a :class:`Window` by ID (deprecated).

        .. deprecated:: 0.16
           Use :meth:`.windows.get()`.
        """
        warnings.warn(
            "Session.get_by_id() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.windows.get(window_id=session_id, default=None)

    def where(self, kwargs: dict[str, t.Any]) -> list[Window]:
        """Filter windows by given criteria (deprecated).

        .. deprecated:: 0.16
           Use :meth:`.windows.filter()`.
        """
        warnings.warn(
            "Session.where() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        try:
            return self.windows.filter(**kwargs)
        except IndexError:
            return []

    def find_where(self, kwargs: dict[str, t.Any]) -> Window | None:
        """Return the first matching :class:`Window` (deprecated).

        .. deprecated:: 0.16
           Use :meth:`.windows.get()`.
        """
        warnings.warn(
            "Session.find_where() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.windows.get(default=None, **kwargs)

    def _list_windows(self) -> list[WindowDict]:
        """Return a list of window dictionaries (deprecated).

        .. deprecated:: 0.16
           Use :attr:`.windows`.
        """
        warnings.warn(
            "Session._list_windows() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return [w.__dict__ for w in self.windows]

    @property
    def _windows(self) -> list[WindowDict]:
        """Alias to :meth:`.list_windows` (deprecated).

        .. deprecated:: 0.16
           Use :attr:`.windows`.
        """
        warnings.warn(
            "Session._windows is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self._list_windows()

    def list_windows(self) -> list[Window]:
        """Return a list of :class:`Window` objects from this session (deprecated).

        .. deprecated:: 0.16
           Use :attr:`.windows`.
        """
        warnings.warn(
            "Session.list_windows() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.windows

    @property
    def children(self) -> QueryList[Window]:
        """Return child windows (deprecated).

        .. deprecated:: 0.16
           Use :attr:`.windows`.
        """
        warnings.warn(
            "Session.children is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.windows
