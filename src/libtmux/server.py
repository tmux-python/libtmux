"""Pythonization of the :term:`tmux(1)` server.

libtmux.server
~~~~~~~~~~~~~~

"""
import logging
import os
import pathlib
import shutil
import subprocess
import typing as t
import warnings

from libtmux._internal.query_list import QueryList
from libtmux.common import tmux_cmd
from libtmux.neo import fetch_objs
from libtmux.pane import Pane
from libtmux.session import Session
from libtmux.window import Window

from . import exc, formats
from .common import (
    EnvironmentMixin,
    PaneDict,
    SessionDict,
    WindowDict,
    has_gte_version,
    session_check_name,
)

logger = logging.getLogger(__name__)


class Server(EnvironmentMixin):
    """
    The :term:`tmux(1)` :term:`Server` [server_manual]_.

    - :attr:`Server.sessions` [:class:`Session`, ...]

      - :attr:`Session.windows` [:class:`Window`, ...]

        - :attr:`Window.panes` [:class:`Pane`, ...]

          - :class:`Pane`

    When instantiated stores information on live, running tmux server.

    Parameters
    ----------
    socket_name : str, optional
    socket_path : str, optional
    config_file : str, optional
    colors : str, optional

    Examples
    --------
    >>> server
    Server(socket_name=libtmux_test...)

    >>> server.sessions
    [Session($1 ...)]

    >>> server.sessions[0].windows
    [Window(@1 1:..., Session($1 ...)]

    >>> server.sessions[0].attached_window
    Window(@1 1:..., Session($1 ...))

    >>> server.sessions[0].attached_pane
    Pane(%1 Window(@1 1:..., Session($1 ...)))

    References
    ----------
    .. [server_manual] CLIENTS AND SESSIONS. openbsd manpage for TMUX(1)
           "The tmux server manages clients, sessions, windows and panes.
           Clients are attached to sessions to interact with them, either when
           they are created with the new-session command, or later with the
           attach-session command. Each session has one or more windows linked
           into it. Windows may be linked to multiple sessions and are made up
           of one or more panes, each of which contains a pseudo terminal."

       https://man.openbsd.org/tmux.1#CLIENTS_AND_SESSIONS.
       Accessed April 1st, 2018.
    """

    socket_name = None
    """Passthrough to ``[-L socket-name]``"""
    socket_path = None
    """Passthrough to ``[-S socket-path]``"""
    config_file = None
    """Passthrough to ``[-f file]``"""
    colors = None
    """``-2`` or ``-8``"""
    child_id_attribute = "session_id"
    """Unique child ID used by :class:`~libtmux.common.TmuxRelationalObject`"""
    formatter_prefix = "server_"
    """Namespace used for :class:`~libtmux.common.TmuxMappingObject`"""

    def __init__(
        self,
        socket_name: t.Optional[str] = None,
        socket_path: t.Optional[t.Union[str, pathlib.Path]] = None,
        config_file: t.Optional[str] = None,
        colors: t.Optional[int] = None,
        **kwargs: t.Any,
    ) -> None:
        EnvironmentMixin.__init__(self, "-g")
        self._windows: t.List[WindowDict] = []
        self._panes: t.List[PaneDict] = []

        if socket_path is not None:
            self.socket_path = socket_path
        elif socket_name is not None:
            self.socket_name = socket_name

        tmux_tmpdir = pathlib.Path(os.getenv("TMUX_TMPDIR", "/tmp"))
        socket_name = self.socket_name or "default"
        if (
            tmux_tmpdir is not None
            and self.socket_path is None
            and self.socket_name is None
            and socket_name != "default"
        ):
            self.socket_path = str(tmux_tmpdir / f"tmux-{os.geteuid()}" / socket_name)

        if config_file:
            self.config_file = config_file

        if colors:
            self.colors = colors

    def is_alive(self) -> bool:
        """If server alive or not.

        >>> tmux = Server(socket_name="no_exist")
        >>> assert not tmux.is_alive()
        """
        try:
            res = self.cmd("list-sessions")
            return res.returncode == 0
        except Exception:
            return False

    def raise_if_dead(self) -> None:
        """Raise if server not connected.

        >>> tmux = Server(socket_name="no_exist")
        >>> try:
        ...     tmux.raise_if_dead()
        ... except Exception as e:
        ...     print(type(e))
        <class 'subprocess.CalledProcessError'>
        """
        tmux_bin = shutil.which("tmux")
        if tmux_bin is None:
            raise exc.TmuxCommandNotFound()

        cmd_args: t.List[str] = ["list-sessions"]
        if self.socket_name:
            cmd_args.insert(0, f"-L{self.socket_name}")
        if self.socket_path:
            cmd_args.insert(0, f"-S{self.socket_path}")
        if self.config_file:
            cmd_args.insert(0, f"-f{self.config_file}")

        subprocess.check_call([tmux_bin] + cmd_args)

    #
    # Command
    #
    def cmd(self, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        """
        Execute tmux command and return output.

        Examples
        --------
        >>> server.cmd('display-message', 'hi')
        <libtmux.common.tmux_cmd object at ...>

        Returns
        -------
        :class:`common.tmux_cmd`

        Notes
        -----
        .. versionchanged:: 0.8

            Renamed from ``.tmux`` to ``.cmd``.
        """

        cmd_args: t.List[t.Union[str, int]] = list(args)
        if self.socket_name:
            cmd_args.insert(0, f"-L{self.socket_name}")
        if self.socket_path:
            cmd_args.insert(0, f"-S{self.socket_path}")
        if self.config_file:
            cmd_args.insert(0, f"-f{self.config_file}")
        if self.colors:
            if self.colors == 256:
                cmd_args.insert(0, "-2")
            elif self.colors == 88:
                cmd_args.insert(0, "-8")
            else:
                raise ValueError("Server.colors must equal 88 or 256")

        return tmux_cmd(*cmd_args, **kwargs)

    @property
    def attached_sessions(self) -> t.List[Session]:
        """
        Return active :class:`Session` objects.

        Examples
        --------
        >>> server.attached_sessions
        []

        Returns
        -------
        list of :class:`Session`
        """
        try:
            sessions = self.sessions
            attached_sessions = list()

            for session in sessions:
                attached = session.session_attached
                # for now session_active is a unicode
                if attached != "0":
                    logger.debug(f"session {session.name} attached")
                    attached_sessions.append(session)
                else:
                    continue

            return attached_sessions
            # return [Session(**s) for s in attached_sessions] or None
        except Exception:
            return []

    def has_session(self, target_session: str, exact: bool = True) -> bool:
        """
        Return True if session exists. ``$ tmux has-session``.

        Parameters
        ----------
        target_session : str
            session name
        exact : bool
            match the session name exactly. tmux uses fnmatch by default.
            Internally prepends ``=`` to the session in ``$ tmux has-session``.
            tmux 2.1 and up only.

        Raises
        ------
        :exc:`exc.BadSessionName`

        Returns
        -------
        bool
        """
        session_check_name(target_session)

        if exact and has_gte_version("2.1"):
            target_session = f"={target_session}"

        proc = self.cmd("has-session", "-t%s" % target_session)

        if not proc.returncode:
            return True

        return False

    def kill_server(self) -> None:
        """``$ tmux kill-server``."""
        self.cmd("kill-server")

    def kill_session(self, target_session: t.Union[str, int]) -> "Server":
        """
        Kill the tmux session with ``$ tmux kill-session``, return ``self``.

        Parameters
        ----------
        target_session : str, optional
            target_session: str. note this accepts ``fnmatch(3)``. 'asdf' will
            kill 'asdfasd'.

        Returns
        -------
        :class:`Server`

        Raises
        ------
        :exc:`exc.BadSessionName`
        """
        proc = self.cmd("kill-session", "-t%s" % target_session)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        return self

    def switch_client(self, target_session: str) -> None:
        """
        ``$ tmux switch-client``.

        Parameters
        ----------
        target_session : str
            name of the session. fnmatch(3) works.

        Raises
        ------
        :exc:`exc.BadSessionName`
        """
        session_check_name(target_session)

        proc = self.cmd("switch-client", "-t%s" % target_session)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def attach_session(self, target_session: t.Optional[str] = None) -> None:
        """``$ tmux attach-session`` aka alias: ``$ tmux attach``.

        Parameters
        ----------
        target_session : str
            name of the session. fnmatch(3) works.

        Raises
        ------
        :exc:`exc.BadSessionName`
        """
        session_check_name(target_session)

        tmux_args: t.Tuple[str, ...] = tuple()
        if target_session:
            tmux_args += ("-t%s" % target_session,)

        proc = self.cmd("attach-session", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def new_session(
        self,
        session_name: t.Optional[str] = None,
        kill_session: bool = False,
        attach: bool = False,
        start_directory: t.Optional[str] = None,
        window_name: t.Optional[str] = None,
        window_command: t.Optional[str] = None,
        *args: t.Any,
        **kwargs: t.Any,
    ) -> Session:
        """
        Return :class:`Session` from  ``$ tmux new-session``.

        Uses ``-P`` flag to print session info, ``-F`` for return formatting
        returns new Session object.

        ``$ tmux new-session -d`` will create the session in the background
        ``$ tmux new-session -Ad`` will move to the session name if it already
        exists. todo: make an option to handle this.

        Parameters
        ----------
        session_name : str, optional
            ::

                $ tmux new-session -s <session_name>
        attach : bool, optional
            create session in the foreground. ``attach=False`` is equivalent
            to::

                $ tmux new-session -d

        Other Parameters
        ----------------
        kill_session : bool, optional
            Kill current session if ``$ tmux has-session``.
            Useful for testing workspaces.
        start_directory : str, optional
            specifies the working directory in which the
            new session is created.
        window_name : str, optional
            ::

                $ tmux new-session -n <window_name>
        window_command : str
            execute a command on starting the session.  The window will close
            when the command exits. NOTE: When this command exits the window
            will close.  This feature is useful for long-running processes
            where the closing of the window upon completion is desired.

        Returns
        -------
        :class:`Session`

        Raises
        ------
        :exc:`exc.BadSessionName`

        Examples
        --------
        Sessions can be created without a session name (0.14.2+):

        >>> server.new_session()
        Session($2 2)

        Creating them in succession will enumerate IDs (via tmux):

        >>> server.new_session()
        Session($3 3)

        With a `session_name`:

        >>> server.new_session(session_name='my session')
        Session($4 my session)
        """
        if session_name is not None:
            session_check_name(session_name)

            if self.has_session(session_name):
                if kill_session:
                    self.cmd("kill-session", "-t%s" % session_name)
                    logger.info("session %s exists. killed it." % session_name)
                else:
                    raise exc.TmuxSessionExists(
                        "Session named %s exists" % session_name
                    )

        logger.debug(f"creating session {session_name}")

        env = os.environ.get("TMUX")

        if env:
            del os.environ["TMUX"]

        tmux_args: t.Tuple[t.Union[str, int], ...] = (
            "-P",
            "-F#{session_id}",  # output
        )

        if session_name is not None:
            tmux_args += (f"-s{session_name}",)

        if not attach:
            tmux_args += ("-d",)

        if start_directory:
            tmux_args += ("-c", start_directory)

        if window_name:
            tmux_args += ("-n", window_name)

        # tmux 2.6 gives unattached sessions a tiny default area
        # no need send in -x/-y if they're in a client already, though
        if has_gte_version("2.6") and "TMUX" not in os.environ:
            tmux_args += ("-x", 800, "-y", 600)

        if window_command:
            tmux_args += (window_command,)

        proc = self.cmd("new-session", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        session_stdout = proc.stdout[0]

        if env:
            os.environ["TMUX"] = env

        session_formatters = dict(
            zip(["session_id"], session_stdout.split(formats.FORMAT_SEPARATOR))
        )

        return Session.from_session_id(
            server=self, session_id=session_formatters["session_id"]
        )

    #
    # Relations
    #
    @property
    def sessions(self) -> QueryList[Session]:  # type:ignore
        """Sessions belonging server.

        Can be accessed via
        :meth:`.sessions.get() <libtmux._internal.query_list.QueryList.get()>` and
        :meth:`.sessions.filter() <libtmux._internal.query_list.QueryList.filter()>`
        """
        sessions: t.List["Session"] = []

        try:
            for obj in fetch_objs(
                list_cmd="list-sessions",
                server=self,
            ):
                sessions.append(Session(server=self, **obj))
        except Exception:
            pass

        return QueryList(sessions)

    @property
    def windows(self) -> QueryList[Window]:  # type:ignore
        """Windows belonging server.

        Can be accessed via
        :meth:`.windows.get() <libtmux._internal.query_list.QueryList.get()>` and
        :meth:`.windows.filter() <libtmux._internal.query_list.QueryList.filter()>`
        """
        windows: t.List["Window"] = []
        for obj in fetch_objs(
            list_cmd="list-windows",
            list_extra_args=("-a",),
            server=self,
        ):
            windows.append(Window(server=self, **obj))

        return QueryList(windows)

    @property
    def panes(self) -> QueryList[Pane]:  # type:ignore
        """Panes belonging server.

        Can be accessed via
        :meth:`.panes.get() <libtmux._internal.query_list.QueryList.get()>` and
        :meth:`.panes.filter() <libtmux._internal.query_list.QueryList.filter()>`
        """
        panes: t.List["Pane"] = []
        for obj in fetch_objs(
            list_cmd="list-panes",
            list_extra_args=["-s"],
            server=self,
        ):
            panes.append(Pane(server=self, **obj))

        return QueryList(panes)

    #
    # Dunder
    #
    def __eq__(self, other: object) -> bool:
        assert isinstance(other, Server)
        return (
            self.socket_name == other.socket_name
            and self.socket_path == other.socket_path
        )

    def __repr__(self) -> str:
        if self.socket_name is not None:
            return (
                f"{self.__class__.__name__}"
                f"(socket_name={getattr(self, 'socket_name', 'default')})"
            )
        elif self.socket_path is not None:
            return (
                f"{self.__class__.__name__}"
                f"(socket_path={getattr(self, 'socket_path')})"
            )
        return f"{self.__class__.__name__}" f"(socket_path=/tmp/tmux-1000/default)"

    #
    # Legacy: Redundant stuff we want to remove
    #
    def _list_panes(self) -> t.List[PaneDict]:
        """
        Return list of panes in :py:obj:`dict` form.

        Retrieved from ``$ tmux(1) list-panes`` stdout.

        The :py:obj:`list` is derived from ``stdout`` in
        :class:`util.tmux_cmd` which wraps :py:class:`subprocess.Popen`.

        .. deprecated:: 0.16
        """
        warnings.warn("Server._list_panes() is deprecated")
        return [p.__dict__ for p in self.panes]

    def _update_panes(self) -> "Server":
        """
        Update internal pane data and return ``self`` for chainability.

        Returns
        -------
        :class:`Server`

        .. deprecated:: 0.16
        """
        warnings.warn("Server._update_panes() is deprecated")
        self._list_panes()
        return self

    def get_by_id(self, id: str) -> t.Optional[Session]:
        """
        .. deprecated:: 0.16
        """
        warnings.warn("Server.get_by_id() is deprecated")
        return self.sessions.get(session_id=id, default=None)

    def where(self, kwargs: t.Dict[str, t.Any]) -> t.List[Session]:
        """
        .. deprecated:: 0.16
        """
        warnings.warn("Server.find_where() is deprecated")
        try:
            return self.sessions.filter(**kwargs)
        except IndexError:
            return []

    def find_where(self, kwargs: t.Dict[str, t.Any]) -> t.Optional[Session]:
        """
        .. deprecated:: 0.16
        """
        warnings.warn("Server.find_where() is deprecated")
        return self.sessions.get(default=None, **kwargs)

    def _list_windows(self) -> t.List[WindowDict]:
        """Return list of windows in :py:obj:`dict` form.

        Retrieved from ``$ tmux(1) list-windows`` stdout.

        The :py:obj:`list` is derived from ``stdout`` in
        :class:`common.tmux_cmd` which wraps :py:class:`subprocess.Popen`.

        .. deprecated:: 0.16
        """
        warnings.warn("Server._list_windows() is deprecated")
        return [w.__dict__ for w in self.windows]

    def _update_windows(self) -> "Server":
        """Update internal window data and return ``self`` for chainability.

        .. deprecated:: 0.16
        """
        warnings.warn("Server._update_windows() is deprecated")
        self._list_windows()
        return self

    @property
    def _sessions(self) -> t.List[SessionDict]:
        """Property / alias to return :meth:`~._list_sessions`.

        .. deprecated:: 0.16
        """
        warnings.warn("Server._sessions is deprecated")
        return self._list_sessions()

    def _list_sessions(self) -> t.List["SessionDict"]:
        """
        .. deprecated:: 0.16
        """
        warnings.warn("Server._list_sessions() is deprecated")
        return [s.__dict__ for s in self.sessions]

    def list_sessions(self) -> t.List[Session]:
        """Return list of :class:`Session` from the ``tmux(1)`` session.

        .. deprecated:: 0.16

        Returns
        -------
        list of :class:`Session`
        """
        warnings.warn("Server.list_sessions is deprecated")
        return self.sessions

    @property
    def children(self) -> QueryList["Session"]:  # type:ignore
        """Was used by TmuxRelationalObject (but that's longer used in this class)

        .. deprecated:: 0.16
        """
        warnings.warn("Server.children is deprecated")
        return self.sessions
