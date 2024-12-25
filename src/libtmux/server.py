"""Wrapper for :term:`tmux(1)` server.

libtmux.server
~~~~~~~~~~~~~~

"""

from __future__ import annotations

import logging
import os
import pathlib
import shutil
import subprocess
import typing as t
import warnings

from libtmux import exc
from libtmux._internal.query_list import QueryList
from libtmux.client import Client
from libtmux.common import get_version, has_gte_version, raise_if_stderr, tmux_cmd
from libtmux.constants import OptionScope
from libtmux.hooks import HooksMixin
from libtmux.neo import fetch_objs, get_output_format, parse_output
from libtmux.pane import Pane
from libtmux.session import Session
from libtmux.window import Window

from .common import (
    AsyncTmuxCmd,
    EnvironmentMixin,
    PaneDict,
    SessionDict,
    WindowDict,
    session_check_name,
)
from .options import OptionsMixin

if t.TYPE_CHECKING:
    import types
    from typing import TypeAlias

    from typing_extensions import Self

    from libtmux._internal.types import StrPath

    DashLiteral: TypeAlias = t.Literal["-"]

logger = logging.getLogger(__name__)


def _is_daemon_not_up_error(stderr_text: str) -> bool:
    """Return True if the error indicates the tmux server is not running.

    tmux signals this in two ways:
    1. "no server running" (socket exists but no daemon is listening)
    2. "error connecting to ... (No such file or directory)" (socket file is missing)
    """
    return "no server running" in stderr_text or (
        "error connecting to" in stderr_text
        and "No such file or directory" in stderr_text
    )


def _fetch_or_empty(
    server: Server,
    list_cmd: str,
    **kwargs: t.Any,
) -> list[dict[str, t.Any]]:
    """Wrap :func:`fetch_objs`: treat a not-yet-started server as empty.

    A fresh :class:`~libtmux.Server` can be introspected via
    :attr:`Server.sessions`, :attr:`Server.windows`, etc. before the
    daemon is up. Other tmux errors, such as socket permission
    failures, still propagate.
    """
    try:
        return fetch_objs(server=server, list_cmd=list_cmd, **kwargs)  # type: ignore[arg-type]
    except exc.LibTmuxException as e:
        if e.args and _is_daemon_not_up_error(str(e.args[0])):
            return []
        raise


class Server(
    EnvironmentMixin,
    OptionsMixin,
    HooksMixin,
):
    """:term:`tmux(1)` :term:`Server` [server_manual]_.

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
    on_init : callable, optional
    socket_name_factory : callable, optional
    tmux_bin : str or pathlib.Path, optional

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
    """``256`` or ``88``"""
    child_id_attribute = "session_id"
    """Unique child ID used by :class:`~libtmux.common.TmuxRelationalObject`"""
    formatter_prefix = "server_"
    """Namespace used for :class:`~libtmux.common.TmuxMappingObject`"""

    default_option_scope: OptionScope | None = OptionScope.Server
    """For option management."""
    default_hook_scope: OptionScope | None = OptionScope.Server
    """For hook management."""
    tmux_bin: str | None = None
    """Custom path to tmux binary. Falls back to ``shutil.which("tmux")``."""

    def __init__(
        self,
        socket_name: str | None = None,
        socket_path: str | pathlib.Path | None = None,
        config_file: str | None = None,
        colors: int | None = None,
        on_init: t.Callable[[Server], None] | None = None,
        socket_name_factory: t.Callable[[], str] | None = None,
        tmux_bin: str | pathlib.Path | None = None,
        **kwargs: t.Any,
    ) -> None:
        EnvironmentMixin.__init__(self, "-g")
        self.tmux_bin = str(tmux_bin) if tmux_bin is not None else None
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
        """Return True if tmux server alive.

        >>> tmux = Server(socket_name="no_exist")
        >>> assert not tmux.is_alive()
        """
        try:
            res = self.cmd("list-sessions")
        except Exception:
            return False
        return res.returncode == 0

    def raise_if_dead(self) -> None:
        """Raise if server not connected.

        Raises
        ------
        :exc:`exc.TmuxCommandNotFound`
            When the tmux binary cannot be found or executed.
        :class:`subprocess.CalledProcessError`
            When the tmux server is not running (non-zero exit from
            ``list-sessions``).

        >>> tmux = Server(socket_name="no_exist")
        >>> try:
        ...     tmux.raise_if_dead()
        ... except Exception as e:
        ...     print(type(e))
        <class 'subprocess.CalledProcessError'>
        """
        resolved = self.tmux_bin or shutil.which("tmux")
        if resolved is None:
            raise exc.TmuxCommandNotFound

        cmd_args: list[str] = ["list-sessions"]
        if self.socket_name:
            cmd_args.insert(0, f"-L{self.socket_name}")
        if self.socket_path:
            cmd_args.insert(0, f"-S{self.socket_path}")
        if self.config_file:
            cmd_args.insert(0, f"-f{self.config_file}")

        try:
            subprocess.check_call([resolved, *cmd_args])
        except FileNotFoundError:
            raise exc.TmuxCommandNotFound from None

    #
    # Command
    #
    def cmd(
        self,
        cmd: str,
        *args: t.Any,
        target: str | int | None = None,
    ) -> tmux_cmd:
        """Execute tmux command respective of socket name and file, return output.

        Examples
        --------
        >>> server.cmd('display-message', 'hi')
        <libtmux.common.tmux_cmd object at ...>

        New session:

        >>> server.cmd('new-session', '-d', '-P', '-F#{session_id}').stdout[0]
        '$2'

        >>> session.cmd('new-window', '-P').stdout[0]
        'libtmux...:2.0'

        Output of `tmux -L ... new-window -P -F#{window_id}` to a `Window` object:

        >>> Window.from_window_id(
        ...     window_id=session.cmd(
        ...         'new-window', '-P', '-F#{window_id}'
        ...     ).stdout[0],
        ...     server=session.server,
        ... )
        Window(@4 3:..., Session($1 libtmux_...))

        Create a pane from a window:

        >>> window.cmd('split-window', '-P', '-F#{pane_id}').stdout[0]
        '%5'

        Output of `tmux -L ... split-window -P -F#{pane_id}` to a `Pane` object:

        >>> Pane.from_pane_id(pane_id=window.cmd(
        ...     'split-window', '-P', '-F#{pane_id}').stdout[0],
        ...     server=window.server
        ... )
        Pane(%... Window(@... ...:..., Session($1 libtmux_...)))

        Parameters
        ----------
        target : str, optional
            Optional custom target.

        Returns
        -------
        :class:`common.tmux_cmd`

        Notes
        -----
        .. versionchanged:: 0.8

            Renamed from ``.tmux`` to ``.cmd``.
        """
        svr_args: list[str | int] = [cmd]
        cmd_args: list[str | int] = []
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

        return tmux_cmd(*svr_args, *cmd_args, tmux_bin=self.tmux_bin)

    async def acmd(
        self,
        cmd: str,
        *args: t.Any,
        target: str | int | None = None,
    ) -> AsyncTmuxCmd:
        """Execute tmux command respective of socket name and file, return output.

        Examples
        --------
        >>> import asyncio
        >>> async def test_acmd():
        ...     result = await server.acmd('display-message', 'hi')
        ...     print(result.stdout)
        >>> asyncio.run(test_acmd())
        []

        New session:

        >>> async def test_new_session():
        ...     result = await server.acmd(
        ...         'new-session', '-d', '-P', '-F#{session_id}'
        ...     )
        ...     print(result.stdout[0])
        >>> asyncio.run(test_new_session())
        $...

        Output of `tmux -L ... new-window -P -F#{window_id}` to a `Window` object:

        >>> async def test_new_window():
        ...     result = await session.acmd('new-window', '-P', '-F#{window_id}')
        ...     window_id = result.stdout[0]
        ...     window = Window.from_window_id(window_id=window_id, server=server)
        ...     print(window)
        >>> asyncio.run(test_new_window())
        Window(@... ...:..., Session($... libtmux_...))

        Create a pane from a window:

        >>> async def test_split_window():
        ...     result = await server.acmd('split-window', '-P', '-F#{pane_id}')
        ...     print(result.stdout[0])
        >>> asyncio.run(test_split_window())
        %...

        Output of `tmux -L ... split-window -P -F#{pane_id}` to a `Pane` object:

        >>> async def test_pane():
        ...     result = await window.acmd('split-window', '-P', '-F#{pane_id}')
        ...     pane_id = result.stdout[0]
        ...     pane = Pane.from_pane_id(pane_id=pane_id, server=server)
        ...     print(pane)
        >>> asyncio.run(test_pane())
        Pane(%... Window(@... ...:..., Session($1 libtmux_...)))

        Parameters
        ----------
        target : str, optional
            Optional custom target.

        Returns
        -------
        :class:`common.AsyncTmuxCmd`
        """
        svr_args: list[str | int] = [cmd]
        cmd_args: list[str | int] = []
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

        return await AsyncTmuxCmd.run(*svr_args, *cmd_args)

    @property
    def attached_sessions(self) -> list[Session]:
        """Return active :class:`Session` instances.

        Examples
        --------
        >>> server.attached_sessions
        []

        Returns
        -------
        list[:class:`Session`]
            Sessions that are attached.
        """
        return self.sessions.filter(session_attached__noeq="1")

    def has_session(self, target_session: str, exact: bool = True) -> bool:
        """Return True if session exists.

        Parameters
        ----------
        target_session : str
            session name
        exact : bool
            match the session name exactly. tmux uses fnmatch by default.
            Internally prepends ``=`` to the session in ``$ tmux has-session``.

        Raises
        ------
        :exc:`exc.BadSessionName`

        Returns
        -------
        bool
        """
        session_check_name(target_session)

        if exact:
            target_session = f"={target_session}"

        proc = self.cmd("has-session", target=target_session)

        return bool(not proc.returncode)

    def kill(self) -> None:
        """Kill tmux server.

        >>> svr = Server(socket_name="testing")
        >>> svr
        Server(socket_name=testing)

        >>> svr.new_session()
        Session(...)

        >>> svr.is_alive()
        True

        >>> svr.kill()

        >>> svr.is_alive()
        False
        """
        proc = self.cmd("kill-server")
        if proc.stderr:
            stderr_text = " ".join(str(line) for line in proc.stderr)
            if _is_daemon_not_up_error(stderr_text):
                return
            raise exc.LibTmuxException(proc.stderr)
        logger.info("server killed", extra={"tmux_subcommand": "kill-server"})

    def kill_session(self, target_session: str | int) -> Server:
        """Kill tmux session.

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
        proc = self.cmd("kill-session", target=target_session)

        raise_if_stderr(proc, "kill-session")

        return self

    def run_shell(
        self,
        command: str,
        *,
        background: bool | None = None,
        delay: str | None = None,
        as_tmux_command: bool | None = None,
        target_pane: str | None = None,
        cwd: StrPath | None = None,
        show_stderr: bool | None = None,
    ) -> list[str] | None:
        r"""Execute a shell command via ``$ tmux run-shell``.

        Parameters
        ----------
        command : str
            Shell command to execute.
        background : bool, optional
            Run in background (``-b`` flag).
        delay : str, optional
            Delay before execution (``-d`` flag).
        as_tmux_command : bool, optional
            Parse argument as a tmux command instead of a shell command
            (``-C`` flag).
        target_pane : str, optional
            Target pane for output (``-t`` flag).
        cwd : str or PathLike, optional
            Start directory for the shell command (``-c`` flag). When
            omitted, tmux uses the target client's current working
            directory. Requires tmux 3.4+; on older tmux a warning is
            emitted and the kwarg is ignored.

            Note: tmux's ``-c`` is a *start directory*, not subprocess
            semantics. If ``chdir(cwd)`` fails, tmux falls back to the
            user's home directory, then to ``/``, rather than raising
            — unlike Python's ``subprocess.Popen(cwd=)`` which errors
            on a failed chdir.

            .. versionadded:: 0.57
        show_stderr : bool, optional
            Combine the command's stderr into the captured output stream
            (``-E`` flag, maps to ``JOB_SHOWSTDERR``). Requires tmux 3.6+;
            on older tmux a warning is emitted and the kwarg is ignored.

            .. versionadded:: 0.57

        Returns
        -------
        list[str] | None
            Stdout lines, or None when *background* is True. Empty list on
            tmux 3.3a/3.4 (upstream stdout passthrough was broken until 3.5).

        Examples
        --------
        >>> result = server.run_shell('true')
        >>> isinstance(result, list)
        True
        """
        tmux_args: tuple[str, ...] = ()

        if background:
            tmux_args += ("-b",)

        if delay is not None:
            tmux_args += ("-d", delay)

        if as_tmux_command:
            tmux_args += ("-C",)

        if target_pane is not None:
            tmux_args += ("-t", target_pane)

        if cwd is not None:
            if has_gte_version("3.4", tmux_bin=self.tmux_bin):
                tmux_args += ("-c", str(cwd))
            else:
                warnings.warn(
                    "cwd requires tmux 3.4+, ignoring",
                    stacklevel=2,
                )

        if show_stderr:
            if has_gte_version("3.6", tmux_bin=self.tmux_bin):
                tmux_args += ("-E",)
            else:
                warnings.warn(
                    "show_stderr requires tmux 3.6+, ignoring",
                    stacklevel=2,
                )

        tmux_args += (command,)

        proc = self.cmd("run-shell", *tmux_args)

        raise_if_stderr(proc, "run-shell")

        if background:
            return None
        return proc.stdout

    def wait_for(
        self,
        channel: str,
        *,
        lock: bool | None = None,
        unlock: bool | None = None,
        set_flag: bool | None = None,
    ) -> None:
        """Wait for, signal, or lock a channel via ``$ tmux wait-for``.

        Parameters
        ----------
        channel : str
            Channel name.
        lock : bool, optional
            Lock the channel (``-L`` flag).
        unlock : bool, optional
            Unlock the channel (``-U`` flag).
        set_flag : bool, optional
            Set the channel flag and wake waiters (``-S`` flag).

        Examples
        --------
        >>> server.new_session(session_name='wait_test')
        Session(...)
        >>> server.wait_for('test_channel', set_flag=True)
        """
        tmux_args: tuple[str, ...] = ()

        if lock:
            tmux_args += ("-L",)

        if unlock:
            tmux_args += ("-U",)

        if set_flag:
            tmux_args += ("-S",)

        tmux_args += (channel,)

        proc = self.cmd("wait-for", *tmux_args)

        raise_if_stderr(proc, "wait-for")

    def bind_key(
        self,
        key: str,
        command: str,
        *,
        key_table: str | None = None,
        note: str | None = None,
        repeat: bool | None = None,
    ) -> None:
        """Bind a key to a command via ``$ tmux bind-key``.

        Parameters
        ----------
        key : str
            Key to bind (e.g. ``C-a``, ``F12``, ``M-x``).
        command : str
            Tmux command to run when key is pressed.
        key_table : str, optional
            Key table to bind in (``-T`` flag). Defaults to ``prefix``.
        note : str, optional
            Note for the binding (``-N`` flag).
        repeat : bool, optional
            Allow the key to repeat (``-r`` flag).

        Examples
        --------
        >>> server.bind_key('F12', 'display-message test', key_table='root')
        >>> server.unbind_key('F12', key_table='root')
        """
        tmux_args: tuple[str, ...] = ()

        if repeat:
            tmux_args += ("-r",)

        if note is not None:
            tmux_args += ("-N", note)

        if key_table is not None:
            tmux_args += ("-T", key_table)

        tmux_args += (key, command)

        proc = self.cmd("bind-key", *tmux_args)

        raise_if_stderr(proc, "bind-key")

    def unbind_key(
        self,
        key: str | None = None,
        *,
        key_table: str | None = None,
        all_keys: bool | None = None,
        quiet: bool | None = None,
    ) -> None:
        """Unbind a key via ``$ tmux unbind-key``.

        Parameters
        ----------
        key : str, optional
            Key to unbind. Required unless *all_keys* is True.
        key_table : str, optional
            Key table (``-T`` flag). Defaults to ``prefix``.
        all_keys : bool, optional
            Unbind all keys (``-a`` flag).
        quiet : bool, optional
            Suppress errors for missing bindings (``-q`` flag).

        Examples
        --------
        >>> server.bind_key('F11', 'display-message test', key_table='root')
        >>> server.unbind_key('F11', key_table='root')
        """
        tmux_args: tuple[str, ...] = ()

        if all_keys:
            tmux_args += ("-a",)

        if quiet:
            tmux_args += ("-q",)

        if key_table is not None:
            tmux_args += ("-T", key_table)

        if key is not None:
            tmux_args += (key,)

        proc = self.cmd("unbind-key", *tmux_args)

        raise_if_stderr(proc, "unbind-key")

    def list_keys(
        self,
        *,
        key_table: str | None = None,
    ) -> list[str]:
        """List key bindings via ``$ tmux list-keys``.

        Parameters
        ----------
        key_table : str, optional
            Filter by key table (``-T`` flag).

        Returns
        -------
        list[str]
            Key binding lines.

        Examples
        --------
        >>> result = server.list_keys()
        >>> isinstance(result, list)
        True
        """
        tmux_args: tuple[str, ...] = ()

        if key_table is not None:
            tmux_args += ("-T", key_table)

        proc = self.cmd("list-keys", *tmux_args)

        raise_if_stderr(proc, "list-keys")

        return proc.stdout

    def list_commands(self, *, command_name: str | None = None) -> list[str]:
        """List tmux commands via ``$ tmux list-commands``.

        Parameters
        ----------
        command_name : str, optional
            Filter to a specific command.

        Returns
        -------
        list[str]
            Command listing lines.

        Examples
        --------
        >>> result = server.list_commands(command_name='send-keys')
        >>> len(result) >= 1
        True
        """
        tmux_args: tuple[str, ...] = ()

        if command_name is not None:
            tmux_args += (command_name,)

        proc = self.cmd("list-commands", *tmux_args)

        raise_if_stderr(proc, "list-commands")

        return proc.stdout

    def lock_server(self) -> None:
        """Lock the tmux server via ``$ tmux lock-server``.

        Requires an attached client.

        >>> with control_mode() as ctl:
        ...     server.lock_server()
        """
        proc = self.cmd("lock-server")

        raise_if_stderr(proc, "lock-server")

    def server_access(
        self,
        *,
        allow: str | None = None,
        deny: str | None = None,
        list_access: bool | None = None,
        read_only: bool | None = None,
        write: bool | None = None,
    ) -> list[str] | None:
        """Manage server access control via ``$ tmux server-access``.

        Requires tmux 3.3+ (introduced in 3.3).

        Parameters
        ----------
        allow : str, optional
            Allow a user (``-a`` flag).
        deny : str, optional
            Deny a user (``-d`` flag).
        list_access : bool, optional
            List access rules (``-l`` flag).
        read_only : bool, optional
            Force the user to attach read-only (``-r`` flag). Implies
            allow if the user is not already in the ACL. Mutually
            exclusive with *write* — tmux rejects ``-r -w``.
        write : bool, optional
            Allow the user to attach read-write (``-w`` flag). Implies
            allow if the user is not already in the ACL. Mutually
            exclusive with *read_only*.

        Returns
        -------
        list[str] | None
            Access list when *list_access* is True, None otherwise.

        Examples
        --------
        >>> from libtmux.common import has_gte_version
        >>> if has_gte_version("3.3"):
        ...     result = server.server_access(list_access=True)
        ...     assert isinstance(result, list)
        """
        if not has_gte_version("3.3", tmux_bin=self.tmux_bin):
            msg = "server_access requires tmux 3.3+"
            raise exc.LibTmuxException(msg)

        if read_only and write:
            msg = "read_only and write are mutually exclusive (tmux rejects -r -w)"
            raise ValueError(msg)

        tmux_args: tuple[str, ...] = ()

        if allow is not None:
            tmux_args += ("-a", allow)

        if deny is not None:
            tmux_args += ("-d", deny)

        if list_access:
            tmux_args += ("-l",)

        if read_only:
            tmux_args += ("-r",)

        if write:
            tmux_args += ("-w",)

        proc = self.cmd("server-access", *tmux_args)

        raise_if_stderr(proc, "server-access")

        if list_access:
            return proc.stdout
        return None

    def refresh_client(self, *, target_client: str | None = None) -> None:
        """Refresh a client's display via ``$ tmux refresh-client``.

        Requires an attached client.

        Parameters
        ----------
        target_client : str, optional
            Target client (``-t`` flag).

        Examples
        --------
        >>> with control_mode() as ctl:
        ...     server.refresh_client()
        """
        tmux_args: tuple[str, ...] = ()

        if target_client is not None:
            tmux_args += ("-t", target_client)

        proc = self.cmd("refresh-client", *tmux_args)

        raise_if_stderr(proc, "refresh-client")

    def suspend_client(self, *, target_client: str | None = None) -> None:
        """Suspend a client via ``$ tmux suspend-client``.

        Requires an attached client.

        Parameters
        ----------
        target_client : str, optional
            Target client (``-t`` flag).

        Examples
        --------
        >>> with control_mode() as ctl:
        ...     server.suspend_client()
        """
        tmux_args: tuple[str, ...] = ()

        if target_client is not None:
            tmux_args += ("-t", target_client)

        proc = self.cmd("suspend-client", *tmux_args)

        raise_if_stderr(proc, "suspend-client")

    def lock_client(self, *, target_client: str | None = None) -> None:
        """Lock a client via ``$ tmux lock-client``.

        Requires an attached client.

        Parameters
        ----------
        target_client : str, optional
            Target client (``-t`` flag).

        Examples
        --------
        >>> with control_mode() as ctl:
        ...     server.lock_client()
        """
        tmux_args: tuple[str, ...] = ()

        if target_client is not None:
            tmux_args += ("-t", target_client)

        proc = self.cmd("lock-client", *tmux_args)

        raise_if_stderr(proc, "lock-client")

    def detach_client(
        self,
        *,
        target_client: str | None = None,
        shell_command: str | None = None,
    ) -> None:
        """Detach a specific client via ``$ tmux detach-client``.

        Maps to ``$ tmux detach-client [-t <target_client>]``. tmux
        resolves ``-t`` over the global client list (see
        ``cmd-find.c``); the named client may be attached to any
        session, so this method lives on :class:`Server` rather than
        :class:`Session`.

        Parameters
        ----------
        target_client : str, optional
            Client name (``-t`` flag). When omitted, tmux falls back to
            the most-recently-active client.
        shell_command : str, optional
            Run a shell command on the detached client after detach
            (``-E`` flag).

        See Also
        --------
        :meth:`Session.detach_client` : detach every client attached to
            a session (``-s`` flag).
        :meth:`detach_all_clients` : detach every client on the server
            (``-a`` flag).

        .. versionadded:: 0.56

        Examples
        --------
        >>> with control_mode() as ctl:
        ...     server.detach_client(target_client=ctl.client_name)
        """
        tmux_args: tuple[str, ...] = ()

        if shell_command is not None:
            tmux_args += ("-E", shell_command)

        if target_client is not None:
            tmux_args += ("-t", target_client)

        proc = self.cmd("detach-client", *tmux_args)

        raise_if_stderr(proc, "detach-client")

    def detach_all_clients(
        self,
        *,
        keep_client: str | None = None,
        shell_command: str | None = None,
    ) -> None:
        """Detach every client on this server via ``$ tmux detach-client -a``.

        tmux's ``-a`` always preserves one client; when *keep_client* is
        omitted, the most-recently-active client survives.

        Parameters
        ----------
        keep_client : str, optional
            Client to preserve (``-t`` flag). All other clients on the
            server, regardless of which session they are attached to,
            are detached.
        shell_command : str, optional
            Run a shell command on the detached client(s) after detach
            (``-E`` flag).

        See Also
        --------
        :meth:`Session.detach_client` : detach every client attached to
            a session (``-s`` flag).
        :meth:`detach_client` : detach a single named client (``-t``
            flag).

        .. versionadded:: 0.56

        Examples
        --------
        >>> with control_mode() as ctl:
        ...     server.detach_all_clients(keep_client=ctl.client_name)
        """
        tmux_args: tuple[str, ...] = ("-a",)

        if shell_command is not None:
            tmux_args += ("-E", shell_command)

        if keep_client is not None:
            tmux_args += ("-t", keep_client)

        proc = self.cmd("detach-client", *tmux_args)

        raise_if_stderr(proc, "detach-client")

    def confirm_before(
        self,
        command: str,
        *,
        prompt: str | None = None,
        confirm_key: str | None = None,
        default_yes: bool | None = None,
        target_client: str | None = None,
    ) -> None:
        """Run a command after confirmation via ``$ tmux confirm-before``.

        Always uses ``-b`` (background) to avoid blocking the command queue.
        Use ``send-keys -K -c <client>`` to provide the confirmation key.

        Requires tmux 3.3+ for ``-b`` flag support.

        Parameters
        ----------
        command : str
            Tmux command to run after confirmation.
        prompt : str, optional
            Custom prompt text (``-p`` flag).
        confirm_key : str, optional
            Key to accept as confirmation (``-c`` flag). Default is ``y``.
            Requires tmux 3.4+.
        default_yes : bool, optional
            Make Enter default to yes (``-y`` flag). Requires tmux 3.4+.
        target_client : str, optional
            Target client (``-t`` flag).

        Examples
        --------
        Interactive confirmation requires tmux 3.4+; the wrapper itself
        works on 3.3+ but the ``send-keys -K -c <client>`` round-trip
        used here is unreliable on 3.3a:

        >>> from libtmux.common import has_gte_version
        >>> if has_gte_version("3.4"):
        ...     with control_mode() as ctl:
        ...         server.confirm_before(
        ...             'set -g @cf_test yes',
        ...             target_client=ctl.client_name,
        ...         )
        ...         _ = server.cmd('send-keys', '-K', '-c', ctl.client_name, 'y')
        ...         result = server.cmd('show-options', '-gv', '@cf_test').stdout[0]
        ... else:
        ...     result = 'yes'
        >>> result
        'yes'
        """
        if not has_gte_version("3.3", tmux_bin=self.tmux_bin):
            msg = "confirm_before requires tmux 3.3+"
            raise exc.LibTmuxException(msg)

        tmux_args: tuple[str, ...] = ("-b",)

        if prompt is not None:
            tmux_args += ("-p", prompt)

        if confirm_key is not None:
            if has_gte_version("3.4", tmux_bin=self.tmux_bin):
                tmux_args += ("-c", confirm_key)
            else:
                warnings.warn(
                    "confirm_key requires tmux 3.4+, ignoring",
                    stacklevel=2,
                )

        if default_yes:
            if has_gte_version("3.4", tmux_bin=self.tmux_bin):
                tmux_args += ("-y",)
            else:
                warnings.warn(
                    "default_yes requires tmux 3.4+, ignoring",
                    stacklevel=2,
                )

        if target_client is not None:
            tmux_args += ("-t", target_client)

        tmux_args += (command,)

        proc = self.cmd("confirm-before", *tmux_args)

        raise_if_stderr(proc, "confirm-before")

    def command_prompt(
        self,
        template: str,
        *,
        prompt: str | None = None,
        inputs: str | None = None,
        target_client: str | None = None,
        one_key: bool | None = None,
        key_only: bool | None = None,
        on_input_change: bool | None = None,
        numeric: bool | None = None,
        prompt_type: t.Literal["command", "search", "target", "window-target"]
        | None = None,
        expand_format: bool | None = None,
        literal: bool | None = None,
        bspace_exit: bool | None = None,
    ) -> None:
        """Open a command prompt via ``$ tmux command-prompt``.

        Always uses ``-b`` (background) to avoid blocking the command queue.
        Use ``send-keys -K -c <client>`` to type into the prompt and submit.

        Requires tmux 3.3+ for ``-b`` flag support.

        Parameters
        ----------
        template : str
            Tmux command template. Use ``%1``, ``%2`` for prompt values.
        prompt : str, optional
            Custom prompt text (``-p`` flag). Commas separate multiple prompts.
        inputs : str, optional
            Pre-fill prompt input (``-I`` flag). Commas separate multiple.
        target_client : str, optional
            Target client (``-t`` flag).
        one_key : bool, optional
            Accept only one key press (``-1`` flag).
        key_only : bool, optional
            Only accept key presses, not text (``-k`` flag).
        on_input_change : bool, optional
            Run template on each keystroke (``-i`` flag).
        numeric : bool, optional
            Accept only numeric input (``-N`` flag).
        prompt_type : str, optional
            Prompt type (``-T`` flag).
        expand_format : bool, optional
            Pass the template through ``args_make_commands_prepare``
            (``-F`` flag) so format strings expand. Requires tmux 3.3+.
        literal : bool, optional
            Disable splitting *prompt* on commas — treat it as a single
            prompt (``-l`` flag). Requires tmux 3.6+.
        bspace_exit : bool, optional
            Close the prompt when the user empties it with backspace
            (``-e`` flag, ``PROMPT_BSPACE_EXIT``). Requires tmux 3.7+ (upstream master).

        Examples
        --------
        Interactive prompts require tmux 3.4+; the wrapper itself works
        on 3.3+ but the ``send-keys -K -c <client>`` round-trip used
        here is unreliable on 3.3a:

        >>> from libtmux.common import has_gte_version
        >>> if has_gte_version("3.4"):
        ...     with control_mode() as ctl:
        ...         server.command_prompt(
        ...             "set -g @cp_test '%1'",
        ...             target_client=ctl.client_name,
        ...         )
        ...         for key in ['h', 'i', 'Enter']:
        ...             _ = server.cmd('send-keys', '-K', '-c', ctl.client_name, key)
        ...         result = server.cmd('show-options', '-gv', '@cp_test').stdout[0]
        ... else:
        ...     result = 'hi'
        >>> result
        'hi'
        """
        if not has_gte_version("3.3", tmux_bin=self.tmux_bin):
            msg = "command_prompt requires tmux 3.3+"
            raise exc.LibTmuxException(msg)

        tmux_args: tuple[str, ...] = ("-b",)

        if one_key:
            tmux_args += ("-1",)

        if key_only:
            tmux_args += ("-k",)

        if on_input_change:
            tmux_args += ("-i",)

        if numeric:
            tmux_args += ("-N",)

        if expand_format:
            tmux_args += ("-F",)

        if literal:
            if has_gte_version("3.6", tmux_bin=self.tmux_bin):
                tmux_args += ("-l",)
            else:
                warnings.warn(
                    "literal requires tmux 3.6+, ignoring",
                    stacklevel=2,
                )

        if bspace_exit:
            if has_gte_version("3.7", tmux_bin=self.tmux_bin):
                tmux_args += ("-e",)
            else:
                warnings.warn(
                    "bspace_exit requires tmux 3.7+ (upstream master), ignoring",
                    stacklevel=2,
                )

        if prompt is not None:
            tmux_args += ("-p", prompt)

        if inputs is not None:
            tmux_args += ("-I", inputs)

        if prompt_type is not None:
            tmux_args += ("-T", prompt_type)

        if target_client is not None:
            tmux_args += ("-t", target_client)

        tmux_args += (template,)

        proc = self.cmd("command-prompt", *tmux_args)

        raise_if_stderr(proc, "command-prompt")

    def display_menu(
        self,
        *items: str,
        title: str | None = None,
        target_pane: str | None = None,
        target_client: str | None = None,
        x: int | str | None = None,
        y: int | str | None = None,
        starting_choice: int | str | None = None,
        border_lines: str | None = None,
        style: str | None = None,
        border_style: str | None = None,
        selected_style: str | None = None,
        mouse: bool | None = None,
        stay_open: bool | None = None,
    ) -> None:
        """Display a popup menu via ``$ tmux display-menu``.

        Requires a TTY-backed attached client. Control-mode clients have
        ``tty.sy=0``, which causes ``menu_prepare()`` to return NULL.
        This method cannot be tested with
        :class:`~libtmux._internal.control_mode.ControlMode`.

        Parameters
        ----------
        *items : str
            Menu items as positional args in tmux's ``name key command``
            triple format. Use empty strings for separators.
        title : str, optional
            Menu title (``-T`` flag).
        target_pane : str, optional
            Target pane for format expansion (``-t`` flag).
        target_client : str, optional
            Target client (``-c`` flag).
        x : int or str, optional
            Menu x position (``-x`` flag).
        y : int or str, optional
            Menu y position (``-y`` flag).
        starting_choice : int or str, optional
            Pre-selected item index (``-C`` flag). Use ``-`` for none.
            Requires tmux 3.4+.
        border_lines : str, optional
            Border line style (``-b`` flag). Requires tmux 3.4+.
        style : str, optional
            Menu style (``-s`` flag). Requires tmux 3.4+.
        border_style : str, optional
            Border style (``-S`` flag). Requires tmux 3.4+.
        selected_style : str, optional
            Style for the currently selected menu item (``-H`` flag).
            Requires tmux 3.4+.
        mouse : bool, optional
            Always enable mouse handling in the menu (``-M`` flag).
            Requires tmux 3.5+.
        stay_open : bool, optional
            Keep the menu open when the mouse is released (``-O`` flag).
            Requires tmux 3.2+.

        Examples
        --------
        Cannot run end-to-end (requires a TTY-backed client; see the
        ``tty.sy=0`` note above). For broader coverage, see
        ``tests/test_server.py::test_display_menu_flags``.

        >>> captured = []
        >>> def fake_cmd(name, *args, **_kw):
        ...     captured.append((name, args))
        ...     return type('R', (), {'stderr': [], 'stdout': []})()
        >>> monkeypatch.setattr(server, 'cmd', fake_cmd)
        >>> server.display_menu('First', '1', 'select-pane', title='menu')
        >>> captured[0][0]
        'display-menu'
        """
        tmux_args: tuple[str, ...] = ()

        if title is not None:
            tmux_args += ("-T", title)

        if target_client is not None:
            tmux_args += ("-c", target_client)

        if target_pane is not None:
            tmux_args += ("-t", target_pane)

        if x is not None:
            tmux_args += ("-x", str(x))

        if y is not None:
            tmux_args += ("-y", str(y))

        if starting_choice is not None:
            if has_gte_version("3.4", tmux_bin=self.tmux_bin):
                tmux_args += ("-C", str(starting_choice))
            else:
                warnings.warn(
                    "starting_choice requires tmux 3.4+, ignoring",
                    stacklevel=2,
                )

        if border_lines is not None:
            if has_gte_version("3.4", tmux_bin=self.tmux_bin):
                tmux_args += ("-b", border_lines)
            else:
                warnings.warn(
                    "border_lines requires tmux 3.4+, ignoring",
                    stacklevel=2,
                )

        if style is not None:
            if has_gte_version("3.4", tmux_bin=self.tmux_bin):
                tmux_args += ("-s", style)
            else:
                warnings.warn(
                    "style requires tmux 3.4+, ignoring",
                    stacklevel=2,
                )

        if border_style is not None:
            if has_gte_version("3.4", tmux_bin=self.tmux_bin):
                tmux_args += ("-S", border_style)
            else:
                warnings.warn(
                    "border_style requires tmux 3.4+, ignoring",
                    stacklevel=2,
                )

        if selected_style is not None:
            if has_gte_version("3.4", tmux_bin=self.tmux_bin):
                tmux_args += ("-H", selected_style)
            else:
                warnings.warn(
                    "selected_style requires tmux 3.4+, ignoring",
                    stacklevel=2,
                )

        if mouse:
            if has_gte_version("3.5", tmux_bin=self.tmux_bin):
                tmux_args += ("-M",)
            else:
                warnings.warn(
                    "mouse requires tmux 3.5+, ignoring",
                    stacklevel=2,
                )

        if stay_open:
            tmux_args += ("-O",)

        tmux_args += items

        proc = self.cmd("display-menu", *tmux_args)

        raise_if_stderr(proc, "display-menu")

    def start_server(self) -> None:
        """Start the tmux server via ``$ tmux start-server``.

        Usually not needed since the server starts automatically on first
        session creation.

        >>> server.start_server()
        """
        proc = self.cmd("start-server")

        raise_if_stderr(proc, "start-server")

    def show_messages(
        self,
        *,
        target_client: str | None = None,
        terminals: bool | None = None,
        jobs: bool | None = None,
    ) -> list[str]:
        """Show server message log via ``$ tmux show-messages``.

        Without ``-T``/``-J``, tmux resolves the message log against a
        target client; if no client is attached and *target_client* is
        omitted, tmux raises ``no current client``. Provide
        *target_client* (e.g. via :class:`~libtmux._internal.control_mode.ControlMode`)
        when running headless, or use *terminals*/*jobs* — those modes
        don't require a client.

        Parameters
        ----------
        target_client : str, optional
            Target client (``-t`` flag).
        terminals : bool, optional
            List terminal capabilities and flags instead of the message
            log (``-T`` flag).
        jobs : bool, optional
            Print the tmux job server summary instead of the message
            log (``-J`` flag).

        Returns
        -------
        list[str]
            Server message log lines (or terminal/job summary when
            *terminals*/*jobs* is set).

        Examples
        --------
        >>> with control_mode() as ctl:
        ...     result = server.show_messages(target_client=ctl.client_name)
        >>> isinstance(result, list)
        True
        """
        tmux_args: tuple[str, ...] = ()

        if terminals:
            tmux_args += ("-T",)

        if jobs:
            tmux_args += ("-J",)

        if target_client is not None:
            tmux_args += ("-t", target_client)

        proc = self.cmd("show-messages", *tmux_args)

        raise_if_stderr(proc, "show-messages")

        return proc.stdout

    @t.overload
    def display_message(
        self,
        cmd: str,
        get_text: t.Literal[True],
        *,
        format_string: str | None = ...,
        all_formats: bool | None = ...,
        verbose: bool | None = ...,
        no_expand: bool | None = ...,
        target_client: str | None = ...,
        delay: int | None = ...,
        notify: bool | None = ...,
    ) -> list[str]: ...

    @t.overload
    def display_message(
        self,
        cmd: str,
        get_text: t.Literal[False] = ...,
        *,
        format_string: str | None = ...,
        all_formats: bool | None = ...,
        verbose: bool | None = ...,
        no_expand: bool | None = ...,
        target_client: str | None = ...,
        delay: int | None = ...,
        notify: bool | None = ...,
    ) -> None: ...

    def display_message(
        self,
        cmd: str,
        get_text: bool = False,
        *,
        format_string: str | None = None,
        all_formats: bool | None = None,
        verbose: bool | None = None,
        no_expand: bool | None = None,
        target_client: str | None = None,
        delay: int | None = None,
        notify: bool | None = None,
    ) -> list[str] | None:
        """Display message at server scope via ``$ tmux display-message``.

        Like :meth:`Pane.display_message` but without ``-t <pane-id>`` injection.
        tmux's ``cmd-display-message`` entry uses ``CMD_FIND_CANFAIL`` so the
        target is optional; server-scoped format reads (``#{version}``,
        ``#{socket_path}``, ``#{pid}``) resolve without a specific pane handle.

        With no client attached and ``target_client`` omitted, the status-line
        path (``get_text=False``) issues a ``no current client`` warning. Use
        ``get_text=True`` for headless reads, or pair with
        :class:`~libtmux._internal.control_mode.ControlMode`.

        Notes
        -----
        Stderr from tmux is reported via :func:`warnings.warn`, not raised.
        tmux uses stderr for both genuine errors and informational messages,
        and the right escalation depends on tmux version and call shape.
        Callers that want to escalate to an exception can wrap the call in
        :func:`warnings.catch_warnings` with ``filterwarnings("error")``.

        .. versionchanged:: 0.57
           Reports stderr via :func:`warnings.warn` instead of raising.

        Parameters
        ----------
        cmd : str
            Format string to display or evaluate (e.g. ``"#{version}"``).
            Pass ``""`` together with ``all_formats=True`` to dump every
            variable.

            .. versionadded:: 0.57
        get_text : bool, optional
            Return tmux's stdout instead of rendering to the status line
            (``-p`` flag).

            .. versionadded:: 0.57
        format_string : str, optional
            Alternative format template (``-F`` flag).

            .. versionadded:: 0.57
        all_formats : bool, optional
            List all format variables (``-a`` flag).

            .. versionadded:: 0.57
        verbose : bool, optional
            Show format variable types (``-v`` flag).

            .. versionadded:: 0.57
        no_expand : bool, optional
            Output the literal string without format expansion (``-l`` flag).
            Requires tmux 3.4+.

            .. versionadded:: 0.57
        target_client : str, optional
            Target client (``-c`` flag).

            .. versionadded:: 0.57
        delay : int, optional
            Display time in milliseconds (``-d`` flag).

            .. versionadded:: 0.57
        notify : bool, optional
            Do not wait for input (``-N`` flag).

            .. versionadded:: 0.57

        Returns
        -------
        list[str] | None
            Message output if ``get_text`` is True, otherwise ``None``.

        Examples
        --------
        Read tmux version without needing a pane handle:

        >>> result = server.display_message("#{version}", get_text=True)
        >>> isinstance(result, list) and len(result) == 1
        True

        Dump every format variable:

        >>> result = server.display_message("", get_text=True, all_formats=True)
        >>> any("session_name=" in line for line in result)
        True
        """
        tmux_args: tuple[str, ...] = ()

        if get_text:
            tmux_args += ("-p",)

        if all_formats:
            tmux_args += ("-a",)

        if verbose:
            tmux_args += ("-v",)

        if no_expand:
            if has_gte_version("3.4", tmux_bin=self.tmux_bin):
                tmux_args += ("-l",)
            else:
                warnings.warn(
                    "no_expand requires tmux 3.4+, ignoring",
                    stacklevel=2,
                )

        if notify:
            tmux_args += ("-N",)

        if target_client is not None:
            tmux_args += ("-c", target_client)

        if delay is not None:
            tmux_args += ("-d", str(delay))

        if format_string is not None:
            tmux_args += ("-F", format_string)

        if cmd:
            tmux_args += (cmd,)

        proc = self.cmd("display-message", *tmux_args)
        if proc.stderr:
            warnings.warn(
                f"display-message: {'; '.join(proc.stderr)}",
                stacklevel=2,
            )

        if get_text:
            return proc.stdout

        return None

    def show_prompt_history(
        self,
        *,
        prompt_type: t.Literal["command", "search", "target", "window-target"]
        | None = None,
    ) -> list[str]:
        """Show prompt history via ``$ tmux show-prompt-history``.

        Parameters
        ----------
        prompt_type : str, optional
            Prompt type to show (``-T`` flag).

        Returns
        -------
        list[str]
            Prompt history lines.

        Examples
        --------
        >>> from libtmux.common import has_gte_version
        >>> if has_gte_version("3.3"):
        ...     result = server.show_prompt_history()
        ... else:
        ...     result = []
        >>> isinstance(result, list)
        True
        """
        if not has_gte_version("3.3", tmux_bin=self.tmux_bin):
            msg = "show_prompt_history requires tmux 3.3+"
            raise exc.LibTmuxException(msg)

        tmux_args: tuple[str, ...] = ()

        if prompt_type is not None:
            tmux_args += ("-T", prompt_type)

        proc = self.cmd("show-prompt-history", *tmux_args)

        raise_if_stderr(proc, "show-prompt-history")

        return proc.stdout

    def clear_prompt_history(
        self,
        *,
        prompt_type: t.Literal["command", "search", "target", "window-target"]
        | None = None,
    ) -> None:
        """Clear prompt history via ``$ tmux clear-prompt-history``.

        Parameters
        ----------
        prompt_type : str, optional
            Prompt type to clear (``-T`` flag).

        Examples
        --------
        >>> from libtmux.common import has_gte_version
        >>> if has_gte_version("3.3"):
        ...     server.clear_prompt_history()
        """
        if not has_gte_version("3.3", tmux_bin=self.tmux_bin):
            msg = "clear_prompt_history requires tmux 3.3+"
            raise exc.LibTmuxException(msg)

        tmux_args: tuple[str, ...] = ()

        if prompt_type is not None:
            tmux_args += ("-T", prompt_type)

        proc = self.cmd("clear-prompt-history", *tmux_args)

        raise_if_stderr(proc, "clear-prompt-history")

    def set_buffer(
        self,
        data: str,
        *,
        buffer_name: str | None = None,
        append: bool | None = None,
    ) -> None:
        """Set a paste buffer via ``$ tmux set-buffer``.

        Parameters
        ----------
        data : str
            Data to store in the buffer.
        buffer_name : str, optional
            Name of the buffer (``-b`` flag).
        append : bool, optional
            Append to the buffer instead of replacing (``-a`` flag).

        Examples
        --------
        >>> server.set_buffer('hello')
        >>> server.show_buffer()
        'hello'
        """
        tmux_args: tuple[str, ...] = ()

        if append:
            tmux_args += ("-a",)

        if buffer_name is not None:
            tmux_args += ("-b", buffer_name)

        tmux_args += (data,)

        proc = self.cmd("set-buffer", *tmux_args)

        raise_if_stderr(proc, "set-buffer")

    def show_buffer(self, *, buffer_name: str | None = None) -> str:
        """Show content of a paste buffer via ``$ tmux show-buffer``.

        Parameters
        ----------
        buffer_name : str, optional
            Name of the buffer (``-b`` flag). Defaults to the most recent.

        Returns
        -------
        str
            Buffer content.

        Examples
        --------
        >>> server.set_buffer('test_data')
        >>> server.show_buffer()
        'test_data'
        """
        tmux_args: tuple[str, ...] = ()

        if buffer_name is not None:
            tmux_args += ("-b", buffer_name)

        proc = self.cmd("show-buffer", *tmux_args)

        raise_if_stderr(proc, "show-buffer")

        return "\n".join(proc.stdout)

    def delete_buffer(self, *, buffer_name: str | None = None) -> None:
        """Delete a paste buffer via ``$ tmux delete-buffer``.

        Parameters
        ----------
        buffer_name : str, optional
            Name of the buffer to delete (``-b`` flag). Defaults to the most
            recent.

        Examples
        --------
        >>> server.set_buffer('to_delete', buffer_name='del_buf')
        >>> server.delete_buffer(buffer_name='del_buf')
        """
        tmux_args: tuple[str, ...] = ()

        if buffer_name is not None:
            tmux_args += ("-b", buffer_name)

        proc = self.cmd("delete-buffer", *tmux_args)

        raise_if_stderr(proc, "delete-buffer")

    def save_buffer(
        self,
        path: StrPath,
        *,
        buffer_name: str | None = None,
        append: bool | None = None,
    ) -> None:
        """Save a paste buffer to a file via ``$ tmux save-buffer``.

        Parameters
        ----------
        path : str or PathLike
            File path to save the buffer to.
        buffer_name : str, optional
            Name of the buffer (``-b`` flag). Defaults to the most recent.
        append : bool, optional
            Append to the file instead of overwriting (``-a`` flag).

        Examples
        --------
        >>> import pathlib
        >>> server.set_buffer('save_me')
        >>> path = pathlib.Path(request.config.rootdir) / '..' / 'tmp_save.txt'
        >>> server.save_buffer(str(path))
        """
        tmux_args: tuple[str, ...] = ()

        if append:
            tmux_args += ("-a",)

        if buffer_name is not None:
            tmux_args += ("-b", buffer_name)

        tmux_args += (str(pathlib.Path(path).expanduser()),)

        proc = self.cmd("save-buffer", *tmux_args)

        raise_if_stderr(proc, "save-buffer")

    def load_buffer(
        self,
        path: StrPath,
        *,
        buffer_name: str | None = None,
    ) -> None:
        """Load a file into a paste buffer via ``$ tmux load-buffer``.

        Parameters
        ----------
        path : str or PathLike
            File path to load into the buffer.
        buffer_name : str, optional
            Name of the buffer (``-b`` flag).

        Examples
        --------
        >>> import pathlib
        >>> path = pathlib.Path(request.config.rootdir) / '..' / 'tmp_load.txt'
        >>> _ = path.write_text('loaded')
        >>> server.load_buffer(str(path), buffer_name='loaded_buf')
        """
        tmux_args: tuple[str, ...] = ()

        if buffer_name is not None:
            tmux_args += ("-b", buffer_name)

        tmux_args += (str(pathlib.Path(path).expanduser()),)

        proc = self.cmd("load-buffer", *tmux_args)

        raise_if_stderr(proc, "load-buffer")

    def list_buffers(
        self,
        *,
        format_string: str | None = None,
        filter: str | None = None,  # noqa: A002
    ) -> list[str]:
        """List paste buffers via ``$ tmux list-buffers``.

        Without arguments returns tmux's default template
        (``name: N bytes: "sample"``) — kept for backward compatibility.
        Pass *format_string* to request a specific tmux format, or *filter*
        to have tmux return only matching buffers.

        Parameters
        ----------
        format_string : str, optional
            Output template (``-F`` flag). Example: ``"#{buffer_name}"`` for
            raw names only.

            .. versionadded:: 0.57
        filter : str, optional
            Filter expression evaluated by tmux (``-f`` flag). Buffers for
            which the expanded expression is false are omitted. Example:
            ``"#{m:libtmux_mcp_*,#{buffer_name}}"``.

            Note: this kwarg shadows the Python builtin ``filter`` by design —
            it mirrors tmux's own flag name (``-f filter``) for grep-friendly
            symmetry between the wrapper and the tmux manual.

            .. warning::

                tmux silently expands a malformed filter (unclosed
                ``#{...}``, unknown format token) to empty, which the
                filter treats as false — every row is suppressed and no
                stderr is emitted. A bad filter is
                indistinguishable from "filter matched nothing"; verify
                filter syntax against the FORMATS section of ``tmux(1)``.

            .. versionadded:: 0.57

        Returns
        -------
        list[str]
            Raw output lines.

        Examples
        --------
        Default template (backward-compatible):

        >>> server.set_buffer('buf_data')
        >>> result = server.list_buffers()
        >>> len(result) >= 1
        True

        Project just the names:

        >>> server.set_buffer('hello', buffer_name='gap6_demo')
        >>> 'gap6_demo' in server.list_buffers(format_string='#{buffer_name}')
        True

        Filter via tmux:

        >>> matches = server.list_buffers(
        ...     format_string='#{buffer_name}',
        ...     filter='#{m:gap6_*,#{buffer_name}}',
        ... )
        >>> 'gap6_demo' in matches
        True
        """
        tmux_args: tuple[str, ...] = ()

        if format_string is not None:
            tmux_args += ("-F", format_string)

        if filter is not None:
            tmux_args += ("-f", filter)

        proc = self.cmd("list-buffers", *tmux_args)

        raise_if_stderr(proc, "list-buffers")

        return proc.stdout

    def if_shell(
        self,
        shell_command: str,
        tmux_command: str,
        *,
        else_command: str | None = None,
        background: bool | None = None,
        target_pane: str | None = None,
    ) -> None:
        """Execute a tmux command conditionally via ``$ tmux if-shell``.

        Parameters
        ----------
        shell_command : str
            Shell command whose exit status determines which tmux command runs.
        tmux_command : str
            Tmux command to run if *shell_command* succeeds (exit 0).
        else_command : str, optional
            Tmux command to run if *shell_command* fails (non-zero exit).
        background : bool, optional
            Run the shell command in the background (``-b`` flag).
        target_pane : str, optional
            Target pane for format expansion (``-t`` flag).

        Examples
        --------
        >>> server.if_shell('true', 'set -g @if_test yes')
        >>> server.cmd('show-options', '-gv', '@if_test').stdout[0]
        'yes'
        """
        tmux_args: tuple[str, ...] = ()

        if background:
            tmux_args += ("-b",)

        if target_pane is not None:
            tmux_args += ("-t", target_pane)

        tmux_args += (shell_command, tmux_command)

        if else_command is not None:
            tmux_args += (else_command,)

        proc = self.cmd("if-shell", *tmux_args)

        raise_if_stderr(proc, "if-shell")

    def source_file(
        self,
        path: StrPath,
        *,
        quiet: bool | None = None,
        parse_only: bool | None = None,
        verbose: bool | None = None,
    ) -> None:
        """Source a tmux configuration file via ``$ tmux source-file``.

        Parameters
        ----------
        path : str or PathLike
            Path to the configuration file.
        quiet : bool, optional
            Suppress errors for missing files (``-q`` flag).
        parse_only : bool, optional
            Check syntax only, do not execute (``-n`` flag).
        verbose : bool, optional
            Show parsed commands (``-v`` flag).

        Examples
        --------
        >>> import pathlib
        >>> conf = pathlib.Path(request.config.rootdir) / '..' / 'tmp_src.conf'
        >>> _ = conf.write_text('set -g @test_source yes')
        >>> server.source_file(str(conf))
        """
        tmux_args: tuple[str, ...] = ()

        if quiet:
            tmux_args += ("-q",)

        if parse_only:
            tmux_args += ("-n",)

        if verbose:
            tmux_args += ("-v",)

        tmux_args += (str(pathlib.Path(path).expanduser()),)

        proc = self.cmd("source-file", *tmux_args)

        raise_if_stderr(proc, "source-file")

    def list_clients(self) -> list[str]:
        """List connected clients via ``$ tmux list-clients``.

        Returns
        -------
        list[str]
            Raw output lines from list-clients.

        Examples
        --------
        >>> isinstance(server.list_clients(), list)
        True
        """
        proc = self.cmd("list-clients")

        raise_if_stderr(proc, "list-clients")

        return proc.stdout

    def switch_client(self, target_session: str) -> None:
        """Switch tmux client.

        Parameters
        ----------
        target_session : str
            name of the session. fnmatch(3) works.

        Raises
        ------
        :exc:`exc.BadSessionName`
        """
        session_check_name(target_session)

        proc = self.cmd("switch-client", target=target_session)

        raise_if_stderr(proc, "switch-client")

    def attach_session(self, target_session: str | None = None) -> None:
        """Attach tmux session.

        Parameters
        ----------
        target_session : str
            name of the session. fnmatch(3) works.

        Raises
        ------
        :exc:`exc.BadSessionName`
        """
        session_check_name(target_session)
        proc = self.cmd("attach-session", target=target_session)

        raise_if_stderr(proc, "attach-session")

    def new_session(
        self,
        session_name: str | None = None,
        kill_session: bool = False,
        attach: bool = False,
        start_directory: StrPath | None = None,
        window_name: str | None = None,
        window_command: str | None = None,
        x: int | DashLiteral | None = None,
        y: int | DashLiteral | None = None,
        environment: dict[str, str] | None = None,
        *args: t.Any,
        detach_others: bool | None = None,
        no_size: bool | None = None,
        client_flags: str | None = None,
        **kwargs: t.Any,
    ) -> Session:
        """Create new session, returns new :class:`Session`.

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
        start_directory : str or PathLike, optional
            specifies the working directory in which the
            new session is created.
        window_name : str, optional
            ::

                $ tmux new-session -n <window_name>
        window_command : str, optional
            execute a command on starting the session.  The window will close
            when the command exits. NOTE: When this command exits the window
            will close.  This feature is useful for long-running processes
            where the closing of the window upon completion is desired.
        x : int | str, optional
            Force the specified width instead of the tmux default for a
            detached session
        y : int | str, optional
            Force the specified height instead of the tmux default for a
            detached session
        detach_others : bool, optional
            Detach other clients from the session (``-D`` flag).

            .. versionadded:: 0.56
        no_size : bool, optional
            Do not set the initial window size (``-X`` flag).

            .. versionadded:: 0.56
        client_flags : str, optional
            Set client flags (``-f`` flag), e.g. ``no-output``,
            ``read-only``. Requires tmux 3.2+.

            .. versionadded:: 0.56

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
                    proc = self.cmd("kill-session", target=session_name)
                    raise_if_stderr(proc, "kill-session")
                    logger.info(
                        "existing session killed",
                        extra={
                            "tmux_session": session_name,
                            "tmux_subcommand": "kill-session",
                        },
                    )
                else:
                    msg = f"Session named {session_name} exists"
                    raise exc.TmuxSessionExists(
                        msg,
                    )

        extra: dict[str, str] = {
            "tmux_subcommand": "new-session",
        }
        if session_name is not None:
            extra["tmux_session"] = str(session_name)
        logger.debug("creating session", extra=extra)

        env = os.environ.get("TMUX")

        if env:
            del os.environ["TMUX"]

        try:
            tmux_version = str(get_version(tmux_bin=self.tmux_bin))
            _fields, format_string = get_output_format("list-sessions", tmux_version)

            tmux_args: tuple[str | int, ...] = (
                "-P",
                f"-F{format_string}",
            )

            if detach_others:
                tmux_args += ("-D",)

            if no_size:
                tmux_args += ("-X",)

            if client_flags is not None:
                tmux_args += ("-f", client_flags)

            if session_name is not None:
                tmux_args += (f"-s{session_name}",)

            if not attach:
                tmux_args += ("-d",)

            if start_directory:
                start_directory = pathlib.Path(start_directory).expanduser()
                tmux_args += ("-c", str(start_directory))

            if window_name:
                tmux_args += ("-n", window_name)

            if x is not None:
                tmux_args += ("-x", x)

            if y is not None:
                tmux_args += ("-y", y)

            if environment:
                for k, v in environment.items():
                    tmux_args += (f"-e{k}={v}",)

            if window_command:
                tmux_args += (window_command,)

            proc = self.cmd("new-session", *tmux_args)

            raise_if_stderr(proc, "new-session")

            session_stdout = proc.stdout[0]

        finally:
            if env:
                os.environ["TMUX"] = env

        session_data = parse_output(session_stdout, "list-sessions", tmux_version)

        session = Session(server=self, **session_data)

        info_extra: dict[str, str] = {
            "tmux_subcommand": "new-session",
        }
        if session.session_name is not None:
            info_extra["tmux_session"] = str(session.session_name)
        logger.info("session created", extra=info_extra)

        return session

    #
    # Relations
    #
    @property
    def sessions(self) -> QueryList[Session]:
        """Sessions contained in server.

        Can be accessed via
        :meth:`.sessions.get() <libtmux._internal.query_list.QueryList.get()>` and
        :meth:`.sessions.filter() <libtmux._internal.query_list.QueryList.filter()>`

        Returns an empty :class:`~libtmux._internal.query_list.QueryList` when
        tmux's ``list-sessions`` fails for any reason — no running daemon, a
        missing socket, a permission error, or a subprocess failure. To
        distinguish "no sessions" from "tmux unreachable", call
        :meth:`Server.is_alive` or :meth:`Server.raise_if_dead`.
        """
        try:
            sessions: list[Session] = [
                Session(server=self, **obj)
                for obj in fetch_objs(server=self, list_cmd="list-sessions")
            ]
        except exc.LibTmuxException:
            return QueryList([])
        return QueryList(sessions)

    @property
    def windows(self) -> QueryList[Window]:
        """Windows contained in server's sessions.

        Can be accessed via
        :meth:`.windows.get() <libtmux._internal.query_list.QueryList.get()>` and
        :meth:`.windows.filter() <libtmux._internal.query_list.QueryList.filter()>`
        """
        windows: list[Window] = [
            Window(server=self, **obj)
            for obj in _fetch_or_empty(
                server=self,
                list_cmd="list-windows",
                list_extra_args=("-a",),
            )
        ]

        return QueryList(windows)

    @property
    def panes(self) -> QueryList[Pane]:
        """Panes contained in tmux server (across all windows in all sessions).

        Can be accessed via
        :meth:`.panes.get() <libtmux._internal.query_list.QueryList.get()>` and
        :meth:`.panes.filter() <libtmux._internal.query_list.QueryList.filter()>`
        """
        panes: list[Pane] = [
            Pane(server=self, **obj)
            for obj in _fetch_or_empty(
                server=self,
                list_cmd="list-panes",
                list_extra_args=("-a",),
            )
        ]

        return QueryList(panes)

    @property
    def clients(self) -> QueryList[Client]:
        """Clients attached to this tmux server.

        Each attached terminal is a separate :class:`Client`. ``server.clients``
        returns the typed view; ``client.client_readonly``, ``client.client_termtype``,
        ``client.client_session`` etc. read tmux's ``client_*`` format tokens.

        Returns an empty :class:`~libtmux._internal.query_list.QueryList` when
        tmux's ``list-clients`` fails for any reason — no running daemon, a
        missing socket, a permission error, or a subprocess failure. To
        distinguish "no clients attached" from "tmux unreachable", call
        :meth:`Server.is_alive` or :meth:`Server.raise_if_dead`.

        Returns
        -------
        :class:`~libtmux._internal.query_list.QueryList` of :class:`Client`

        Examples
        --------
        >>> with control_mode() as ctl:
        ...     names = [c.client_name for c in server.clients]
        ...     ctl.client_name in names
        True
        """
        try:
            clients: list[Client] = [
                Client(server=self, **obj)
                for obj in fetch_objs(server=self, list_cmd="list-clients")
            ]
        except exc.LibTmuxException:
            return QueryList([])
        return QueryList(clients)

    def search_sessions(
        self,
        *,
        filter: str | None = None,  # noqa: A002
    ) -> QueryList[Session]:
        """Sessions, optionally filtered by tmux before rows are returned.

        Like :attr:`Server.sessions` but adds an optional ``filter`` kwarg
        passed to ``$ tmux list-sessions -f <filter>``.

        Parameters
        ----------
        filter : str, optional
            tmux format expression (``-f`` flag). tmux omits sessions whose
            expanded expression is false before libtmux builds objects.

            .. warning::

                tmux silently expands a malformed filter (unclosed
                ``#{...}``, unknown format token) to empty, which the
                filter treats as false — every row is suppressed and no
                stderr is emitted. A bad filter is
                indistinguishable from "filter matched nothing"; verify
                filter syntax against the FORMATS section of ``tmux(1)``.

            .. versionadded:: 0.57

        Returns
        -------
        :class:`~libtmux._internal.query_list.QueryList` of :class:`Session`

        See Also
        --------
        :attr:`Server.sessions` : unfiltered :class:`QueryList` of every
            session (Python-side ``.filter()`` runs against this).
        :ref:`native-filtering` : when to pick ``search_*`` over
            ``QueryList.filter()``.

        Examples
        --------
        >>> server.new_session(session_name='gap7_alpha')
        Session($... gap7_alpha)
        >>> server.new_session(session_name='other_beta')
        Session($... other_beta)
        >>> matches = server.search_sessions(filter='#{m:gap7_*,#{session_name}}')
        >>> [s.session_name for s in matches]
        ['gap7_alpha']
        """
        sessions: list[Session] = [
            Session(server=self, **obj)
            for obj in _fetch_or_empty(
                server=self,
                list_cmd="list-sessions",
                filter=filter,
            )
        ]
        return QueryList(sessions)

    def search_windows(
        self,
        *,
        filter: str | None = None,  # noqa: A002
    ) -> QueryList[Window]:
        """All windows across sessions, optionally filtered by tmux.

        Like :attr:`Server.windows` but with a ``filter`` kwarg passed to
        ``$ tmux list-windows -a -f <filter>``.

        Parameters
        ----------
        filter : str, optional
            tmux format expression (``-f`` flag).

            .. warning::

                tmux silently expands a malformed filter (unclosed
                ``#{...}``, unknown format token) to empty, which the
                filter treats as false — every row is suppressed and no
                stderr is emitted. A bad filter is
                indistinguishable from "filter matched nothing"; verify
                filter syntax against the FORMATS section of ``tmux(1)``.

            .. versionadded:: 0.57

        See Also
        --------
        :attr:`Server.windows` : unfiltered :class:`QueryList` of every
            window across every session (Python-side ``.filter()`` runs
            against this).
        :ref:`native-filtering` : when to pick ``search_*`` over
            ``QueryList.filter()``.

        Examples
        --------
        >>> sess = server.new_session(session_name='gap7_win_demo')
        >>> _ = sess.new_window(window_name='gap7_target')
        >>> _ = sess.new_window(window_name='other_window')
        >>> matches = server.search_windows(filter='#{m:gap7_*,#{window_name}}')
        >>> any(w.window_name == 'gap7_target' for w in matches)
        True
        >>> any(w.window_name == 'other_window' for w in matches)
        False
        """
        windows: list[Window] = [
            Window(server=self, **obj)
            for obj in _fetch_or_empty(
                server=self,
                list_cmd="list-windows",
                list_extra_args=("-a",),
                filter=filter,
            )
        ]

        return QueryList(windows)

    def search_panes(
        self,
        *,
        filter: str | None = None,  # noqa: A002
    ) -> QueryList[Pane]:
        """All panes across the server, optionally filtered by tmux.

        Like :attr:`Server.panes` but with a ``filter`` kwarg passed to
        ``$ tmux list-panes -a -f <filter>``. tmux drops non-matching panes
        before libtmux builds objects.

        Parameters
        ----------
        filter : str, optional
            tmux format expression (``-f`` flag). Example:
            ``'#{m:%5,#{pane_id}}'`` (id match) or
            ``'#{C/i:libtmux,#{pane_current_command}}'`` (case-insensitive
            substring on the current command).

            .. warning::

                tmux silently expands a malformed filter (unclosed
                ``#{...}``, unknown format token) to empty, which the
                filter treats as false — every row is suppressed and no
                stderr is emitted. A bad filter is
                indistinguishable from "filter matched nothing"; verify
                filter syntax against the FORMATS section of ``tmux(1)``.

            .. versionadded:: 0.57

        See Also
        --------
        :attr:`Server.panes` : unfiltered :class:`QueryList` of every
            pane (Python-side ``.filter()`` runs against this).
        :ref:`native-filtering` : when to pick ``search_*`` over
            ``QueryList.filter()``.

        Examples
        --------
        >>> sess = server.new_session(session_name='gap7_pane_demo')
        >>> window = sess.active_window
        >>> target_pane = window.split()
        >>> matches = server.search_panes(
        ...     filter=f'#{{m:{target_pane.pane_id},#{{pane_id}}}}'
        ... )
        >>> [p.pane_id for p in matches] == [target_pane.pane_id]
        True
        """
        panes: list[Pane] = [
            Pane(server=self, **obj)
            for obj in _fetch_or_empty(
                server=self,
                list_cmd="list-panes",
                list_extra_args=("-a",),
                filter=filter,
            )
        ]

        return QueryList(panes)

    #
    # Dunder
    #
    def __eq__(self, other: object) -> bool:
        """Equal operator for :class:`Server` object."""
        if isinstance(other, Server):
            return (
                self.socket_name == other.socket_name
                and self.socket_path == other.socket_path
            )
        return False

    def __repr__(self) -> str:
        """Representation of :class:`Server` object."""
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

    #
    # Legacy: Redundant stuff we want to remove
    #
    def kill_server(self) -> None:
        """Kill tmux server.

        Notes
        -----
        .. deprecated:: 0.30

           Deprecated in favor of :meth:`.kill()`.

        """
        raise exc.DeprecatedError(
            deprecated="Server.kill_server()",
            replacement="Server.kill()",
            version="0.30.0",
        )

    def _list_panes(self) -> list[PaneDict]:
        """Return list of panes in :py:obj:`dict` form.

        Retrieved from ``$ tmux(1) list-panes`` stdout.

        The :py:obj:`list` is derived from ``stdout`` in
        :class:`util.tmux_cmd` which wraps :py:class:`subprocess.Popen`.

        .. deprecated:: 0.17

           Deprecated in favor of :attr:`.panes`.

        """
        raise exc.DeprecatedError(
            deprecated="Server._list_panes()",
            replacement="Server.panes property",
            version="0.17.0",
        )

    def _update_panes(self) -> Server:
        """Update internal pane data and return ``self`` for chainability.

        .. deprecated:: 0.17

           Deprecated in favor of :attr:`.panes` and returning ``self``.

        Returns
        -------
        :class:`Server`
        """
        raise exc.DeprecatedError(
            deprecated="Server._update_panes()",
            replacement="Server.panes property",
            version="0.17.0",
        )

    def get_by_id(self, session_id: str) -> Session | None:
        """Return session by id. Deprecated in favor of :meth:`.sessions.get()`.

        .. deprecated:: 0.16

           Deprecated by :meth:`.sessions.get()`.

        """
        raise exc.DeprecatedError(
            deprecated="Server.get_by_id()",
            replacement="Server.sessions.get(session_id=..., default=None)",
            version="0.16.0",
        )

    def where(self, kwargs: dict[str, t.Any]) -> list[Session]:
        """Filter through sessions, return list of :class:`Session`.

        .. deprecated:: 0.17

           Deprecated by :meth:`.session.filter()`.

        """
        raise exc.DeprecatedError(
            deprecated="Server.where()",
            replacement="Server.sessions.filter()",
            version="0.17.0",
        )

    def find_where(self, kwargs: dict[str, t.Any]) -> Session | None:
        """Filter through sessions, return first :class:`Session`.

        .. deprecated:: 0.17

           Slated to be removed in favor of :meth:`.sessions.get()`.

        """
        raise exc.DeprecatedError(
            deprecated="Server.find_where()",
            replacement="Server.sessions.get(default=None, **kwargs)",
            version="0.17.0",
        )

    def _list_windows(self) -> list[WindowDict]:
        """Return list of windows in :py:obj:`dict` form.

        Retrieved from ``$ tmux(1) list-windows`` stdout.

        The :py:obj:`list` is derived from ``stdout`` in
        :class:`common.tmux_cmd` which wraps :py:class:`subprocess.Popen`.

        .. deprecated:: 0.17

           Slated to be removed in favor of :attr:`.windows`.

        """
        raise exc.DeprecatedError(
            deprecated="Server._list_windows()",
            replacement="Server.windows property",
            version="0.17.0",
        )

    def _update_windows(self) -> Server:
        """Update internal window data and return ``self`` for chainability.

        .. deprecated:: 0.17

           Deprecated in favor of :attr:`.windows` and returning ``self``.

        """
        raise exc.DeprecatedError(
            deprecated="Server._update_windows()",
            replacement="Server.windows property",
            version="0.17.0",
        )

    @property
    def _sessions(self) -> list[SessionDict]:
        """Property / alias to return :meth:`~._list_sessions`.

        .. deprecated:: 0.17

           Slated to be removed in favor of :attr:`.sessions`.

        """
        raise exc.DeprecatedError(
            deprecated="Server._sessions",
            replacement="Server.sessions property",
            version="0.17.0",
        )

    def _list_sessions(self) -> list[SessionDict]:
        """Return list of session object dictionaries.

        .. deprecated:: 0.17

           Slated to be removed in favor of :attr:`.sessions`.
        """
        raise exc.DeprecatedError(
            deprecated="Server._list_sessions()",
            replacement="Server.sessions property",
            version="0.17.0",
        )

    def list_sessions(self) -> list[Session]:
        """Return list of :class:`Session` from the ``tmux(1)`` session.

        .. deprecated:: 0.17

           Slated to be removed in favor of :attr:`.sessions`.

        Returns
        -------
        list of :class:`Session`
        """
        raise exc.DeprecatedError(
            deprecated="Server.list_sessions()",
            replacement="Server.sessions property",
            version="0.17.0",
        )

    @property
    def children(self) -> QueryList[Session]:
        """Was used by TmuxRelationalObject (but that's longer used in this class).

        .. deprecated:: 0.17

           Slated to be removed in favor of :attr:`.sessions`.

        """
        raise exc.DeprecatedError(
            deprecated="Server.children",
            replacement="Server.sessions property",
            version="0.17.0",
        )
