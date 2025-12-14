"""Pythonization of the :term:`tmux(1)` session.

libtmux.session
~~~~~~~~~~~~~~~

"""

from __future__ import annotations

import dataclasses
import logging
import pathlib
import typing as t

from libtmux._internal.query_list import QueryList
from libtmux.common import tmux_cmd
from libtmux.constants import WINDOW_DIRECTION_FLAG_MAP, OptionScope, WindowDirection
from libtmux.formats import FORMAT_SEPARATOR
from libtmux.hooks import HooksMixin
from libtmux.neo import Obj, fetch_obj, fetch_objs
from libtmux.options import OptionsMixin
from libtmux.pane import Pane
from libtmux.window import Window

from . import exc
from .common import (
    EnvironmentMixin,
    WindowDict,
    session_check_name,
)

if t.TYPE_CHECKING:
    import sys
    import types

    from libtmux._internal.types import StrPath
    from libtmux.common import tmux_cmd

    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing_extensions import Self

    from .server import Server


logger = logging.getLogger(__name__)


@dataclasses.dataclass()
class Session(
    Obj,
    EnvironmentMixin,
    OptionsMixin,
    HooksMixin,
):
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
           management of tmux.  Each session has one or more windows linked to
           it."

       https://man.openbsd.org/tmux.1#DESCRIPTION. Accessed April 1st, 2018.
    """

    default_option_scope: OptionScope | None = None
    default_hook_scope: OptionScope | None = None
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
    def windows(self) -> QueryList[Window]:
        """Windows contained by session.

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
        """Panes contained by session's windows.

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

    #
    # Command
    #
    def cmd(
        self,
        cmd: str,
        *args: t.Any,
        target: str | int | None = None,
    ) -> tmux_cmd:
        """Execute tmux subcommand within session context.

        Automatically binds target by adding  ``-t`` for object's session ID to the
        command. Pass ``target`` to keyword arguments to override.

        Examples
        --------
        >>> session.cmd('new-window', '-P').stdout[0]
        'libtmux...:....0'

        From raw output to an enriched `Window` object:

        >>> Window.from_window_id(window_id=session.cmd(
        ... 'new-window', '-P', '-F#{window_id}').stdout[0], server=session.server)
        Window(@... ...:..., Session($1 libtmux_...))

        Parameters
        ----------
        target : str, optional
            Optional custom target override. By default, the target is the session ID.

        Returns
        -------
        :meth:`server.cmd`

        Notes
        -----
        .. versionchanged:: 0.34

           Passing target by ``-t`` is ignored. Use ``target`` keyword argument instead.

        .. versionchanged:: 0.8

            Renamed from ``.tmux`` to ``.cmd``.
        """
        if target is None:
            target = self.session_id
        return self.server.cmd(cmd, *args, target=target)

    """
    Commands (tmux-like)
    """

    def select_window(self, target_window: str | int) -> Window:
        """Select window and return the selected window.

        Parameters
        ----------
        window : str
            ``target_window`` can also be 'last-window' (``-l``), 'next-window'
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
        target = f"{self.session_id}:{target_window}"

        proc = self.cmd("select-window", target=target)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        return self.active_window

    #
    # Computed properties
    #
    @property
    def active_pane(self) -> Pane | None:
        """Return the active :class:`Pane` object."""
        return self.active_window.active_pane

    @property
    def active_window(self) -> Window:
        """Return the active :class:`Window` object."""
        active_windows = self.windows.filter(window_active="1")

        if len(active_windows) == 1:
            return next(iter(active_windows))
        if len(active_windows) == 0:
            raise exc.NoActiveWindow
        raise exc.MultipleActiveWindows(count=len(active_windows))

        if len(self._windows) == 0:
            raise exc.NoWindowsExist
        return None

    def attach(
        self,
        exit_: bool | None = None,
        flags_: list[str] | None = None,
    ) -> Session:
        """Return ``$ tmux attach-session`` aka alias: ``$ tmux attach``.

        Examples
        --------
        >>> session = server.new_session()

        >>> session not in server.attached_sessions
        True
        """
        flags: tuple[str, ...] = ()

        if exit_ is not None and exit_:
            flags += ("-x",)

        if flags_ is not None and isinstance(flags_, list):
            flags += tuple(f"{','.join(flags_)}")

        proc = self.cmd(
            "attach-session",
            *flags,
        )

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        return self

    def kill(
        self,
        all_except: bool | None = None,
        clear: bool | None = None,
    ) -> None:
        """Kill :class:`Session`, closes linked windows and detach all clients.

        ``$ tmux kill-session``.

        Parameters
        ----------
        all_except : bool, optional
            Kill all sessions in server except this one.
        clear : bool, optional
            Clear alerts (bell, activity, or silence) in all windows.

        Examples
        --------
        Kill a session:

        >>> session_1 = server.new_session()

        >>> session_1 in server.sessions
        True

        >>> session_1.kill()

        >>> session_1 not in server.sessions
        True

        Kill all sessions except the current one:

        >>> one_session_to_rule_them_all = server.new_session()

        >>> other_sessions = server.new_session(
        ...     ), server.new_session()

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

        if clear:  # Clear alerts (bell, activity, or silence) in all windows
            flags += ("-C",)

        proc = self.cmd(
            "kill-session",
            *flags,
        )

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def switch_client(self) -> Session:
        """Switch client to session.

        Raises
        ------
        :exc:`exc.LibTmuxException`
        """
        proc = self.cmd("switch-client")

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        return self

    def rename_session(self, new_name: str) -> Session:
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
            raise exc.LibTmuxException(proc.stderr)

        self.refresh()

        return self

    def new_window(
        self,
        window_name: str | None = None,
        *,
        start_directory: StrPath | None = None,
        attach: bool = False,
        window_index: str = "",
        window_shell: str | None = None,
        environment: dict[str, str] | None = None,
        direction: WindowDirection | None = None,
        target_window: str | None = None,
    ) -> Window:
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

        direction : WindowDirection, optional
            Insert window before or after target window.

        target_window : str, optional
            Used by :meth:`Window.new_window` to specify the target window.

        .. versionchanged:: 0.28.0

           ``attach`` default changed from ``True`` to ``False``.

        See Also
        --------
        :meth:`Window.new_window()`

        Examples
        --------
        >>> window_initial = session.new_window(window_name='Example')
        >>> window_initial
        Window(@... 2:Example, Session($1 libtmux_...))
        >>> window_initial.window_index
        '2'

        >>> window_before = session.new_window(
        ... window_name='Window before', direction=WindowDirection.Before)
        >>> window_initial.refresh()
        >>> window_before
        Window(@... 1:Window before, Session($1 libtmux_...))
        >>> window_initial
        Window(@... 3:Example, Session($1 libtmux_...))

        >>> window_after = session.new_window(
        ... window_name='Window after', direction=WindowDirection.After)
        >>> window_initial.refresh()
        >>> window_after.refresh()
        >>> window_after
        Window(@... 3:Window after, Session($1 libtmux_...))
        >>> window_initial
        Window(@... 4:Example, Session($1 libtmux_...))
        >>> window_before
        Window(@... 1:Window before, Session($1 libtmux_...))

        Returns
        -------
        :class:`Window`
            The newly created window.
        """
        window_args: tuple[str, ...] = ()

        if not attach:
            window_args += ("-d",)

        window_args += ("-P",)

        # Catch empty string and default (`None`)
        if start_directory:
            start_directory = pathlib.Path(start_directory).expanduser()
            window_args += (f"-c{start_directory}",)

        window_args += ("-F#{window_id}",)  # output
        if window_name is not None and isinstance(window_name, str):
            window_args += ("-n", window_name)

        if environment:
            for k, v in environment.items():
                window_args += (f"-e{k}={v}",)

        if direction is not None:
            window_args += (WINDOW_DIRECTION_FLAG_MAP[direction],)

        target: str | None = None
        if window_index is not None:
            # empty string for window_index will use the first one available
            target = f"{self.session_id}:{window_index}"
        if target_window:
            target = target_window
        elif window_index is not None:
            # empty string for window_index will use the first one available
            window_args += (f"-t{self.session_id}:{window_index}",)

        if window_shell:
            window_args += (window_shell,)

        cmd = self.cmd("new-window", *window_args, target=target)

        if cmd.stderr:
            raise exc.LibTmuxException(cmd.stderr)

        window_output = cmd.stdout[0]

        window_formatters = dict(
            zip(["window_id"], window_output.split(FORMAT_SEPARATOR), strict=False),
        )

        return Window.from_window_id(
            server=self.server,
            window_id=window_formatters["window_id"],
        )

    def kill_window(self, target_window: str | None = None) -> None:
        """Close a tmux window, and all panes inside it, ``$ tmux kill-window``.

        Kill the current window or the window at ``target-window``. removing it
        from any sessions to which it is linked.

        Parameters
        ----------
        target_window : str, optional
            Window to kill.

        Raises
        ------
        :exc:`libtmux.exc.LibTmuxException`
            If tmux returns an error.
        """
        if target_window:
            if isinstance(target_window, int):
                target = f"{self.window_name}:{target_window}"
            else:
                target = f"{target_window}"

        proc = self.cmd("kill-window", target=target)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

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
    def id(self) -> str | None:
        """Alias of :attr:`Session.session_id`.

        >>> session.id
        '$1'

        >>> session.id == session.session_id
        True
        """
        return self.session_id

    @property
    def name(self) -> str | None:
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
    @property
    def attached_pane(self) -> Pane | None:
        """Return the active :class:`Pane` object.

        Notes
        -----
        .. deprecated:: 0.31

           Deprecated in favor of :meth:`.active_pane`.
        """
        raise exc.DeprecatedError(
            deprecated="Session.attached_pane",
            replacement="Session.active_pane",
            version="0.31.0",
        )

    @property
    def attached_window(self) -> Window:
        """Return the active :class:`Window` object.

        Notes
        -----
        .. deprecated:: 0.31

           Deprecated in favor of :meth:`.active_window`.
        """
        raise exc.DeprecatedError(
            deprecated="Session.attached_window",
            replacement="Session.active_window",
            version="0.31.0",
        )

    def attach_session(self) -> Session:
        """Return ``$ tmux attach-session`` aka alias: ``$ tmux attach``.

        Notes
        -----
        .. deprecated:: 0.30

           Deprecated in favor of :meth:`.attach()`.
        """
        raise exc.DeprecatedError(
            deprecated="Session.attach_session()",
            replacement="Session.attach()",
            version="0.30.0",
        )

    def kill_session(self) -> None:
        """Destroy session.

        Notes
        -----
        .. deprecated:: 0.30

           Deprecated in favor of :meth:`.kill()`.
        """
        raise exc.DeprecatedError(
            deprecated="Session.kill_session()",
            replacement="Session.kill()",
            version="0.30.0",
        )

    def get(self, key: str, default: t.Any | None = None) -> t.Any:
        """Return key-based lookup. Deprecated by attributes.

        .. deprecated:: 0.17

           Deprecated by attribute lookup.e.g. ``session['session_name']`` is now
           accessed via ``session.session_name``.

        """
        raise exc.DeprecatedError(
            deprecated="Session.get()",
            replacement="direct attribute access (e.g., session.session_name)",
            version="0.17.0",
        )

    def __getitem__(self, key: str) -> t.Any:
        """Return item lookup by key. Deprecated in favor of attributes.

        .. deprecated:: 0.17

           Deprecated in favor of attributes. e.g. ``session['session_name']`` is now
           accessed via ``session.session_name``.

        """
        raise exc.DeprecatedError(
            deprecated="Session[key] lookup",
            replacement="direct attribute access (e.g., session.session_name)",
            version="0.17.0",
        )

    def get_by_id(self, session_id: str) -> Window | None:
        """Return window by id. Deprecated in favor of :meth:`.windows.get()`.

        .. deprecated:: 0.16

           Deprecated by :meth:`.windows.get()`.

        """
        raise exc.DeprecatedError(
            deprecated="Session.get_by_id()",
            replacement="Session.windows.get(window_id=..., default=None)",
            version="0.16.0",
        )

    def where(self, kwargs: dict[str, t.Any]) -> list[Window]:
        """Filter through windows, return list of :class:`Window`.

        .. deprecated:: 0.17

           Deprecated by :meth:`.windows.filter()`.

        """
        raise exc.DeprecatedError(
            deprecated="Session.where()",
            replacement="Session.windows.filter()",
            version="0.17.0",
        )

    def find_where(self, kwargs: dict[str, t.Any]) -> Window | None:
        """Filter through windows, return first :class:`Window`.

        .. deprecated:: 0.17

           Slated to be removed in favor of :meth:`.windows.get()`.

        """
        raise exc.DeprecatedError(
            deprecated="Session.find_where()",
            replacement="Session.windows.get(default=None, **kwargs)",
            version="0.17.0",
        )

    def _list_windows(self) -> list[WindowDict]:
        """Return list of windows (deprecated in favor of :attr:`.windows`).

        .. deprecated:: 0.17

           Slated to be removed in favor of :attr:`.windows`.

        """
        raise exc.DeprecatedError(
            deprecated="Session._list_windows()",
            replacement="Session.windows property",
            version="0.17.0",
        )

    @property
    def _windows(self) -> list[WindowDict]:
        """Property / alias to return :meth:`Session._list_windows`.

        .. deprecated:: 0.17

           Slated to be removed in favor of :attr:`.windows`.

        """
        raise exc.DeprecatedError(
            deprecated="Session._windows",
            replacement="Session.windows property",
            version="0.17.0",
        )

    def list_windows(self) -> list[Window]:
        """Return a list of :class:`Window` from the ``tmux(1)`` session.

        .. deprecated:: 0.17

           Slated to be removed in favor of :attr:`.windows`.

        """
        raise exc.DeprecatedError(
            deprecated="Session.list_windows()",
            replacement="Session.windows property",
            version="0.17.0",
        )

    @property
    def children(self) -> QueryList[Window]:
        """Was used by TmuxRelationalObject (but that's longer used in this class).

        .. deprecated:: 0.17

           Slated to be removed in favor of :attr:`.windows`.

        """
        raise exc.DeprecatedError(
            deprecated="Session.children",
            replacement="Session.windows property",
            version="0.17.0",
        )
