"""Wrap the :term:`tmux(1)` server.

This module manages the top-level tmux server, allowing for the creation,
control, and inspection of sessions, windows, and panes across a single server
instance. It provides the :class:`Server` class, which acts as a gateway
to the tmux server process.

libtmux.server
~~~~~~~~~~~~~~

Examples
--------
>>> server.is_alive()  # Check if tmux server is running
True
>>> # Clean up any existing test session first
>>> if server.has_session("test_session"):
...     server.kill_session("test_session")
>>> new_session = server.new_session(session_name="test_session")
>>> new_session.name
'test_session'
>>> server.has_session("test_session")
True
>>> server.kill_session("test_session")  # Clean up
Server(socket_name=libtmux_test...)
"""

from __future__ import annotations

import contextlib
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

if t.TYPE_CHECKING:
    import sys
    import types

    if sys.version_info >= (3, 10):
        from typing import Self, TypeAlias
    else:
        from typing_extensions import Self, TypeAlias

    DashLiteral: TypeAlias = t.Literal["-"]

logger = logging.getLogger(__name__)


class Server(EnvironmentMixin):
    """Represent a :term:`tmux(1)` server [server_manual]_.

    This class provides the ability to create, manage, and destroy tmux
    sessions and their associated windows and panes. It is the top-level
    interface to the tmux server process, allowing you to query and control
    all sessions within it.

    - :attr:`Server.sessions` => list of :class:`Session`

      - :attr:`Session.windows` => list of :class:`Window`

        - :attr:`Window.panes` => list of :class:`Pane`

    When instantiated, it stores information about a live, running tmux server.

    Parameters
    ----------
    socket_name : str, optional
        Equivalent to tmux's ``-L <socket-name>`` option.
    socket_path : str or pathlib.Path, optional
        Equivalent to tmux's ``-S <socket-path>`` option.
    config_file : str, optional
        Equivalent to tmux's ``-f <file>`` option.
    colors : int, optional
        Can be 88 or 256 to specify supported colors (via ``-2`` or ``-8``).
    on_init : callable, optional
    socket_name_factory : callable, optional

    Examples
    --------
    >>> server
    Server(socket_name=libtmux_test...)

    >>> server.sessions
    [Session($1 ...)]

    >>> server.sessions[0].windows
    [Window(@1 1:..., Session($1 ...))]

    >>> server.sessions[0].active_window
    Window(@1 1:..., Session($1 ...))

    >>> server.sessions[0].active_pane
    Pane(%1 Window(@1 1:..., Session($1 ...)))

    The server can be used as a context manager to ensure proper cleanup:

    >>> with Server() as server:
    ...     session = server.new_session()
    ...     # Do work with the session
    ...     # Server will be killed automatically when exiting the context

    References
    ----------
    .. [server_manual] CLIENTS AND SESSIONS. openbsd manpage for TMUX(1)
           "The tmux server manages clients, sessions, windows and panes.
           Clients are attached to sessions to interact with them, either when
           they are created with the new-session command, or later with the
           attach-session command. Each session has one or more windows linked
           into it. Windows may be linked to multiple sessions and are made up
           of one or more panes, each of which contains a pseudo terminal."

       https://man.openbsd.org/tmux.1#CLIENTS_AND_SESSIONS
       Accessed April 1st, 2018.
    """

    socket_name = None
    """Passthrough to ``[-L socket-name]``."""
    socket_path = None
    """Passthrough to ``[-S socket-path]``."""
    config_file = None
    """Passthrough to ``[-f file]``."""
    colors = None
    """May be ``-2`` or ``-8`` depending on color support (256 or 88)."""
    child_id_attribute = "session_id"
    """Unique child ID used by :class:`~libtmux.common.TmuxRelationalObject`."""
    formatter_prefix = "server_"
    """Namespace used for :class:`~libtmux.common.TmuxMappingObject`."""

    def __init__(
        self,
        socket_name: str | None = None,
        socket_path: str | pathlib.Path | None = None,
        config_file: str | None = None,
        colors: int | None = None,
        on_init: t.Callable[[Server], None] | None = None,
        socket_name_factory: t.Callable[[], str] | None = None,
        **kwargs: t.Any,
    ) -> None:
        """Initialize the Server object, optionally specifying socket and config.

        If both ``socket_path`` and ``socket_name`` are provided, ``socket_path``
        takes precedence.

        Parameters
        ----------
        socket_name : str, optional
            Socket name for tmux server (-L flag).
        socket_path : str or pathlib.Path, optional
            Socket path for tmux server (-S flag).
        config_file : str, optional
            Path to a tmux config file (-f flag).
        colors : int, optional
            If 256, pass ``-2`` to tmux; if 88, pass ``-8``.

        Other Parameters
        ----------------
        **kwargs
            Additional keyword arguments are ignored.
        """
        EnvironmentMixin.__init__(self, "-g")
        self._windows: list[WindowDict] = []
        self._panes: list[PaneDict] = []

        if socket_path is not None:
            self.socket_path = socket_path
        elif socket_name is not None:
            self.socket_name = socket_name
        elif socket_name_factory is not None:
            self.socket_name = socket_name_factory()

        tmux_tmpdir = pathlib.Path(os.getenv("TMUX_TMPDIR", "/tmp"))
        socket_name = self.socket_name or "default"

        # If no path is given and socket_name is not the default, build a path
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

        if on_init is not None:
            on_init(self)

    def __enter__(self) -> Self:
        """Enter the context, returning self.

        Returns
        -------
        :class:`Server`
            The server instance
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Exit the context, killing the server if it exists.

        Parameters
        ----------
        exc_type : type[BaseException] | None
            The type of the exception that was raised
        exc_value : BaseException | None
            The instance of the exception that was raised
        exc_tb : types.TracebackType | None
            The traceback of the exception that was raised
        """
        if self.is_alive():
            self.kill()

    def is_alive(self) -> bool:
        """Return True if the tmux server is alive and responding.

        Examples
        --------
        >>> tmux = Server(socket_name="no_exist")
        >>> assert not tmux.is_alive()
        """
        try:
            res = self.cmd("list-sessions")
        except Exception:
            return False
        return res.returncode == 0

    def raise_if_dead(self) -> None:
        """Raise an error if the tmux server is not reachable.

        >>> tmux = Server(socket_name="no_exist")
        >>> try:
        ...     tmux.raise_if_dead()
        ... except Exception as e:
        ...     print(type(e))
        <class 'subprocess.CalledProcessError'>

        Raises
        ------
        exc.TmuxCommandNotFound
            If the tmux binary is not found in PATH.
        subprocess.CalledProcessError
            If the tmux server is not responding properly.
        """
        tmux_bin = shutil.which("tmux")
        if tmux_bin is None:
            raise exc.TmuxCommandNotFound

        cmd_args: list[str] = ["list-sessions"]
        if self.socket_name:
            cmd_args.insert(0, f"-L{self.socket_name}")
        if self.socket_path:
            cmd_args.insert(0, f"-S{self.socket_path}")
        if self.config_file:
            cmd_args.insert(0, f"-f{self.config_file}")

        subprocess.check_call([tmux_bin, *cmd_args])

    def cmd(
        self,
        cmd: str,
        *args: t.Any,
        target: str | int | None = None,
    ) -> tmux_cmd:
        """Execute a tmux command with this server's configured socket and file.

        The returned object contains information about the tmux command
        execution, including stdout, stderr, and exit code.

        Parameters
        ----------
        cmd
            The tmux subcommand to execute (e.g., 'list-sessions').
        *args
            Additional arguments for the subcommand.
        target, optional
            Optional target for the command (usually specifies a session,
            window, or pane).

        Examples
        --------
        >>> server.cmd('display-message', 'hi')
        <libtmux.common.tmux_cmd object at ...>

        New session:

        >>> server.cmd('new-session', '-d', '-P', '-F#{session_id}').stdout[0]
        '$2'

        You can then convert raw tmux output to rich objects:

        >>> from libtmux.window import Window
        >>> Window.from_window_id(
        ...     window_id=session.cmd('new-window', '-P', '-F#{window_id}').stdout[0],
        ...     server=window.server
        ... )
        Window(@3 2:..., Session($1 libtmux_...))

        Create a pane from a window:
        >>> window.cmd('split-window', '-P', '-F#{pane_id}').stdout[0]
        '%4'

        Output of ``tmux -L ... split-window -P -F#{pane_id}`` to a :class:`Pane`:
        >>> Pane.from_pane_id(pane_id=window.cmd(
        ... 'split-window', '-P', '-F#{pane_id}').stdout[0], server=window.server)
        Pane(%... Window(@... ...:..., Session($1 libtmux_...)))

        Returns
        -------
        tmux_cmd
            Object that wraps stdout, stderr, and return code from the tmux call.

        Notes
        -----
        .. versionchanged:: 0.8
           Renamed from ``.tmux`` to ``.cmd``.
        """
        svr_args: list[str | int] = [cmd]

        if self.socket_name:
            svr_args.insert(0, f"-L{self.socket_name}")
        if self.socket_path:
            svr_args.insert(0, f"-S{self.socket_path}")
        if self.config_file:
            svr_args.insert(0, f"-f{self.config_file}")
        if self.colors:
            if self.colors == 256:
                svr_args.insert(0, "-2")
            elif self.colors == 88:
                svr_args.insert(0, "-8")
            else:
                raise exc.UnknownColorOption

        cmd_args = ["-t", str(target), *args] if target is not None else [*args]
        return tmux_cmd(*svr_args, *cmd_args)

    @property
    def attached_sessions(self) -> list[Session]:
        """Return a list of currently attached sessions.

        Attached sessions are those where ``session_attached`` is not '1'.

        Examples
        --------
        >>> server.attached_sessions
        []
        """
        return self.sessions.filter(session_attached__noeq="1")

    def has_session(self, target_session: str, exact: bool = True) -> bool:
        """Return True if session exists.

        Parameters
        ----------
        target_session : str
            Target session name to check
        exact : bool, optional
            If True, match the name exactly. Otherwise, match as a pattern.

        Examples
        --------
        >>> # Clean up any existing test session
        >>> if server.has_session("test_session"):
        ...     server.kill_session("test_session")
        >>> server.new_session(session_name="test_session")
        Session($... test_session)
        >>> server.has_session("test_session")
        True
        >>> server.has_session("nonexistent")
        False
        >>> server.has_session("test_session", exact=True)  # Exact match
        True
        >>> # Pattern matching (using tmux's pattern matching)
        >>> server.has_session("test_sess*", exact=False)  # Pattern match
        True
        >>> server.kill_session("test_session")  # Clean up
        Server(socket_name=libtmux_test...)
        """
        session_check_name(target_session)

        if exact and has_gte_version("2.1"):
            target_session = f"={target_session}"

        proc = self.cmd("has-session", target=target_session)
        return proc.returncode == 0

    def kill(self) -> None:
        """Kill the entire tmux server.

        This closes all sessions, windows, and panes associated with it.

        Examples
        --------
        >>> # Create a new server for testing kill()
        >>> test_server = Server(socket_name="testing")
        >>> test_server.new_session()
        Session(...)
        >>> test_server.is_alive()
        True
        >>> test_server.kill()
        >>> test_server.is_alive()
        False
        """
        self.cmd("kill-server")

    def kill_session(self, target_session: str | int) -> Server:
        """Kill a session by name.

        Parameters
        ----------
        target_session : str or int
            Name of the session or session ID to kill

        Examples
        --------
        >>> # Clean up any existing session first
        >>> if server.has_session("temp"):
        ...     server.kill_session("temp")
        >>> session = server.new_session(session_name="temp")
        >>> server.has_session("temp")
        True
        >>> server.kill_session("temp")
        Server(socket_name=libtmux_test...)
        >>> server.has_session("temp")
        False
        """
        proc = self.cmd("kill-session", target=target_session)
        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)
        return self

    def switch_client(self, target_session: str) -> None:
        """Switch a client to a different session.

        Parameters
        ----------
        target_session
            The name or pattern of the target session.

        Examples
        --------
        >>> # Create two test sessions
        >>> for name in ["session1", "session2"]:
        ...     if server.has_session(name):
        ...         server.kill_session(name)
        >>> session1 = server.new_session(session_name="session1")
        >>> session2 = server.new_session(session_name="session2")
        >>> # Note: switch_client() requires an interactive terminal
        >>> # so we can't demonstrate it in doctests
        >>> # Clean up
        >>> server.kill_session("session1")
        Server(socket_name=libtmux_test...)
        >>> server.kill_session("session2")
        Server(socket_name=libtmux_test...)

        Raises
        ------
        exc.BadSessionName
            If the session name is invalid.
        exc.LibTmuxException
            If tmux reports an error (stderr output).
        """
        session_check_name(target_session)
        proc = self.cmd("switch-client", target=target_session)
        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def attach_session(self, target_session: str | None = None) -> None:
        """Attach to a specific session, making it the active client.

        Parameters
        ----------
        target_session : str, optional
            The name or pattern of the target session. If None, attaches to
            the most recently used session.

        Examples
        --------
        >>> # Create a test session
        >>> if server.has_session("test_attach"):
        ...     server.kill_session("test_attach")
        >>> session = server.new_session(session_name="test_attach")
        >>> # Note: attach_session() requires an interactive terminal
        >>> # so we can't demonstrate it in doctests
        >>> # Clean up
        >>> server.kill_session("test_attach")
        Server(socket_name=libtmux_test...)

        Raises
        ------
        exc.BadSessionName
            If the session name is invalid.
        exc.LibTmuxException
            If tmux reports an error (stderr output).
        """
        session_check_name(target_session)
        proc = self.cmd("attach-session", target=target_session)
        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def new_session(
        self,
        session_name: str | None = None,
        kill_session: bool = False,
        attach: bool = False,
        start_directory: str | None = None,
        window_name: str | None = None,
        window_command: str | None = None,
        x: int | DashLiteral | None = None,
        y: int | DashLiteral | None = None,
        environment: dict[str, str] | None = None,
        *args: t.Any,
        **kwargs: t.Any,
    ) -> Session:
        """Create a new session.

        Parameters
        ----------
        session_name : str, optional
            Name of the session
        kill_session : bool, optional
            Kill session if it exists
        attach : bool, optional
            Attach to session after creating it
        start_directory : str, optional
            Working directory for the session
        window_name : str, optional
            Name of the initial window
        window_command : str, optional
            Command to run in the initial window
        x : int or "-", optional
            Width of new window
        y : int or "-", optional
            Height of new window
        environment : dict, optional
            Dictionary of environment variables to set

        Examples
        --------
        >>> # Clean up any existing sessions first
        >>> for name in ["basic", "custom", "env_test"]:
        ...     if server.has_session(name):
        ...         server.kill_session(name)
        >>> # Create a basic session
        >>> session1 = server.new_session(session_name="basic")
        >>> session1.name
        'basic'

        >>> # Create session with custom window name
        >>> session2 = server.new_session(
        ...     session_name="custom",
        ...     window_name="editor"
        ... )
        >>> session2.windows[0].name
        'editor'

        >>> # Create session with environment variables
        >>> session3 = server.new_session(
        ...     session_name="env_test",
        ...     environment={"TEST_VAR": "test_value"}
        ... )
        >>> session3.name
        'env_test'

        >>> # Clean up
        >>> for name in ["basic", "custom", "env_test"]:
        ...     server.kill_session(name)
        Server(socket_name=libtmux_test...)
        Server(socket_name=libtmux_test...)
        Server(socket_name=libtmux_test...)
        """
        if session_name is not None:
            session_check_name(session_name)

            if self.has_session(session_name):
                if kill_session:
                    self.cmd("kill-session", target=session_name)
                    logger.info(f"session {session_name} exists. killed it.")
                else:
                    msg = f"Session named {session_name} exists."
                    raise exc.TmuxSessionExists(msg)

        logger.debug(f"creating session {session_name}")
        env = os.environ.get("TMUX")
        if env:
            del os.environ["TMUX"]

        tmux_args: list[str | int] = ["-P", "-F#{session_id}"]
        if session_name is not None:
            tmux_args.append(f"-s{session_name}")
        if not attach:
            tmux_args.append("-d")
        if start_directory:
            tmux_args += ["-c", start_directory]
        if window_name:
            tmux_args += ["-n", window_name]
        if x is not None:
            tmux_args += ["-x", x]
        if y is not None:
            tmux_args += ["-y", y]
        if environment:
            if has_gte_version("3.2"):
                for k, v in environment.items():
                    tmux_args.append(f"-e{k}={v}")
            else:
                logger.warning(
                    "Environment flag ignored, tmux 3.2 or newer required.",
                )
        if window_command:
            tmux_args.append(window_command)

        proc = self.cmd("new-session", *tmux_args)
        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        session_stdout = proc.stdout[0]
        if env:
            os.environ["TMUX"] = env

        session_formatters = dict(
            zip(["session_id"], session_stdout.split(formats.FORMAT_SEPARATOR)),
        )
        return Session.from_session_id(
            server=self,
            session_id=session_formatters["session_id"],
        )

    @property
    def sessions(self) -> QueryList[Session]:
        """Return list of sessions.

        Examples
        --------
        >>> # Clean up any existing test sessions first
        >>> for name in ["test1", "test2"]:
        ...     if server.has_session(name):
        ...         server.kill_session(name)
        >>> # Create some test sessions
        >>> session1 = server.new_session(session_name="test1")
        >>> session2 = server.new_session(session_name="test2")
        >>> len(server.sessions) >= 2  # May have other sessions
        True
        >>> sorted([s.name for s in server.sessions if s.name in ["test1", "test2"]])
        ['test1', 'test2']
        >>> # Clean up
        >>> server.kill_session("test1")
        Server(socket_name=libtmux_test...)
        >>> server.kill_session("test2")
        Server(socket_name=libtmux_test...)
        """
        sessions: list[Session] = []
        with contextlib.suppress(Exception):
            sessions.extend(
                Session(server=self, **obj)
                for obj in fetch_objs(
                    list_cmd="list-sessions",
                    server=self,
                )
            )
        return QueryList(sessions)

    @property
    def windows(self) -> QueryList[Window]:
        """Return a :class:`QueryList` of all :class:`Window` objects in this server.

        This includes windows in all sessions.

        Examples
        --------
        >>> # Clean up any existing test sessions
        >>> for name in ["test_windows1", "test_windows2"]:
        ...     if server.has_session(name):
        ...         server.kill_session(name)
        >>> # Create sessions with windows
        >>> session1 = server.new_session(session_name="test_windows1")
        >>> session2 = server.new_session(session_name="test_windows2")
        >>> # Create additional windows
        >>> _ = session1.new_window(window_name="win1")  # Create window
        >>> _ = session2.new_window(window_name="win2")  # Create window
        >>> # Each session should have 2 windows (default + new)
        >>> len([w for w in server.windows if w.session.name == "test_windows1"])
        2
        >>> len([w for w in server.windows if w.session.name == "test_windows2"])
        2
        >>> # Verify window names
        >>> wins1 = [w for w in server.windows if w.session.name == "test_windows1"]
        >>> wins2 = [w for w in server.windows if w.session.name == "test_windows2"]
        >>> sorted(w.name for w in wins1)
        ['win1', ...]
        >>> sorted(w.name for w in wins2)
        ['win2', ...]
        >>> # Clean up
        >>> server.kill_session("test_windows1")
        Server(socket_name=libtmux_test...)
        >>> server.kill_session("test_windows2")
        Server(socket_name=libtmux_test...)

        Access advanced filtering and retrieval with:
        :meth:`.windows.get() <libtmux._internal.query_list.QueryList.get()>` and
        :meth:`.windows.filter() <libtmux._internal.query_list.QueryList.filter()>`
        """
        windows: list[Window] = [
            Window(server=self, **obj)
            for obj in fetch_objs(
                list_cmd="list-windows",
                list_extra_args=("-a",),
                server=self,
            )
        ]
        return QueryList(windows)

    @property
    def panes(self) -> QueryList[Pane]:
        """Return a :class:`QueryList` of all :class:`Pane` objects in this server.

        This includes panes from all windows in all sessions.

        Examples
        --------
        >>> # Clean up any existing test session
        >>> if server.has_session("test_panes"):
        ...     server.kill_session("test_panes")
        >>> # Create a session and split some panes
        >>> session = server.new_session(session_name="test_panes")
        >>> window = session.attached_window
        >>> # Split into two panes
        >>> window.split_window()
        Pane(%... Window(@... 1:..., Session($... test_panes)))
        >>> # Each window starts with 1 pane, split creates another
        >>> len([p for p in server.panes if p.window.session.name == "test_panes"])
        2
        >>> # Clean up
        >>> server.kill_session("test_panes")
        Server(socket_name=libtmux_test...)

        Access advanced filtering and retrieval with:
        :meth:`.panes.get() <libtmux._internal.query_list.QueryList.get()>` and
        :meth:`.panes.filter() <libtmux._internal.query_list.QueryList.filter()>`
        """
        panes: list[Pane] = [
            Pane(server=self, **obj)
            for obj in fetch_objs(
                list_cmd="list-panes",
                list_extra_args=("-a",),
                server=self,
            )
        ]
        return QueryList(panes)

    def __eq__(self, other: object) -> bool:
        """Compare two servers by their socket name/path."""
        if isinstance(other, Server):
            return (
                self.socket_name == other.socket_name
                and self.socket_path == other.socket_path
            )
        return False

    def __repr__(self) -> str:
        """Return a string representation of this :class:`Server`."""
        if self.socket_name is not None:
            return (
                f"{self.__class__.__name__}"
                f"(socket_name={getattr(self, 'socket_name', 'default')})"
            )
        if self.socket_path is not None:
            return f"{self.__class__.__name__}(socket_path={self.socket_path})"
        return (
            f"{self.__class__.__name__}(socket_path=/tmp/tmux-{os.geteuid()}/default)"
        )

    # Deprecated / Legacy Methods

    def kill_server(self) -> None:
        """Kill the tmux server (deprecated).

        .. deprecated:: 0.30
           Use :meth:`.kill()`.
        """
        warnings.warn(
            "Server.kill_server() is deprecated in favor of Server.kill()",
            category=DeprecationWarning,
            stacklevel=2,
        )
        self.cmd("kill-server")

    def _list_panes(self) -> list[PaneDict]:
        """Return a list of all panes in dict form (deprecated).

        .. deprecated:: 0.16
           Use :attr:`.panes`.
        """
        warnings.warn(
            "Server._list_panes() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return [p.__dict__ for p in self.panes]

    def _update_panes(self) -> Server:
        """Update internal pane data (deprecated).

        .. deprecated:: 0.16
           Use :attr:`.panes` instead.
        """
        warnings.warn(
            "Server._update_panes() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        self._list_panes()
        return self

    def get_by_id(self, session_id: str) -> Session | None:
        """Return a session by its ID (deprecated).

        .. deprecated:: 0.16
           Use :meth:`.sessions.get()`.
        """
        warnings.warn(
            "Server.get_by_id() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.sessions.get(session_id=session_id, default=None)

    def where(self, kwargs: dict[str, t.Any]) -> list[Session]:
        """Filter sessions (deprecated).

        .. deprecated:: 0.16
           Use :meth:`.sessions.filter()`.
        """
        warnings.warn(
            "Server.find_where() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        try:
            return self.sessions.filter(**kwargs)
        except IndexError:
            return []

    def find_where(self, kwargs: dict[str, t.Any]) -> Session | None:
        """Return the first matching session (deprecated).

        .. deprecated:: 0.16
           Use :meth:`.sessions.get()`.
        """
        warnings.warn(
            "Server.find_where() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.sessions.get(default=None, **kwargs)

    def _list_windows(self) -> list[WindowDict]:
        """Return a list of all windows in dict form (deprecated).

        .. deprecated:: 0.16
           Use :attr:`.windows`.
        """
        warnings.warn(
            "Server._list_windows() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return [w.__dict__ for w in self.windows]

    def _update_windows(self) -> Server:
        """Update internal window data (deprecated).

        .. deprecated:: 0.16
           Use :attr:`.windows`.
        """
        warnings.warn(
            "Server._update_windows() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        self._list_windows()
        return self

    @property
    def _sessions(self) -> list[SessionDict]:
        """Return session objects in dict form (deprecated).

        .. deprecated:: 0.16
           Use :attr:`.sessions`.
        """
        warnings.warn(
            "Server._sessions is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self._list_sessions()

    def _list_sessions(self) -> list[SessionDict]:
        """Return a list of all sessions in dict form (deprecated).

        .. deprecated:: 0.16
           Use :attr:`.sessions`.
        """
        warnings.warn(
            "Server._list_sessions() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return [s.__dict__ for s in self.sessions]

    def list_sessions(self) -> list[Session]:
        """Return a list of all :class:`Session` objects (deprecated).

        .. deprecated:: 0.16
           Use :attr:`.sessions`.
        """
        warnings.warn(
            "Server.list_sessions is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.sessions

    @property
    def children(self) -> QueryList[Session]:
        """Return child sessions (deprecated).

        .. deprecated:: 0.16
           Use :attr:`.sessions`.
        """
        warnings.warn(
            "Server.children is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.sessions
