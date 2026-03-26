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

from libtmux import exc
from libtmux._internal.query_list import QueryList
from libtmux.common import tmux_cmd
from libtmux.constants import OptionScope
from libtmux.hooks import HooksMixin
from libtmux.neo import fetch_objs, get_output_format, parse_output
from libtmux.pane import Pane
from libtmux.session import Session
from libtmux.window import Window

from .common import (
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

        >>> Window.from_window_id(window_id=session.cmd(
        ... 'new-window', '-P', '-F#{window_id}').stdout[0], server=session.server)
        Window(@4 3:..., Session($1 libtmux_...))

        Create a pane from a window:

        >>> window.cmd('split-window', '-P', '-F#{pane_id}').stdout[0]
        '%5'

        Output of `tmux -L ... split-window -P -F#{pane_id}` to a `Pane` object:

        >>> Pane.from_pane_id(pane_id=window.cmd(
        ... 'split-window', '-P', '-F#{pane_id}').stdout[0], server=window.server)
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
            if (
                "no server running" in stderr_text
                or "error connecting to" in stderr_text
            ):
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

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        return self

    def run_shell(
        self,
        command: str,
        *,
        background: bool | None = None,
        delay: str | None = None,
        capture: bool | None = None,
        target_pane: str | None = None,
    ) -> list[str] | None:
        """Execute a shell command via ``$ tmux run-shell``.

        Parameters
        ----------
        command : str
            Shell command to execute.
        background : bool, optional
            Run in background (``-b`` flag).
        delay : str, optional
            Delay before execution (``-d`` flag).
        capture : bool, optional
            Capture output to the target pane (``-C`` flag).
        target_pane : str, optional
            Target pane for output (``-t`` flag).

        Returns
        -------
        list[str] | None
            Command stdout if not running in background, None otherwise.

        Examples
        --------
        >>> result = server.run_shell('echo hello')
        >>> 'hello' in (result or [])
        True
        """
        tmux_args: tuple[str, ...] = ()

        if background:
            tmux_args += ("-b",)

        if delay is not None:
            tmux_args += ("-d", delay)

        if capture:
            tmux_args += ("-C",)

        if target_pane is not None:
            tmux_args += ("-t", target_pane)

        tmux_args += (command,)

        proc = self.cmd("run-shell", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

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

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

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

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

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

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

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

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

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

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        return proc.stdout

    def lock_server(self) -> None:
        """Lock the tmux server via ``$ tmux lock-server``.

        Requires an attached client.

        Examples
        --------
        >>> with control_mode() as ctl:
        ...     server.lock_server()
        """
        proc = self.cmd("lock-server")

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def server_access(
        self,
        *,
        allow: str | None = None,
        deny: str | None = None,
        list_access: bool | None = None,
    ) -> list[str] | None:
        """Manage server access control via ``$ tmux server-access``.

        Parameters
        ----------
        allow : str, optional
            Allow a user (``-a`` flag).
        deny : str, optional
            Deny a user (``-d`` flag).
        list_access : bool, optional
            List access rules (``-l`` flag).

        Returns
        -------
        list[str] | None
            Access list when *list_access* is True, None otherwise.

        Examples
        --------
        >>> result = server.server_access(list_access=True)
        >>> isinstance(result, list)
        True
        """
        tmux_args: tuple[str, ...] = ()

        if allow is not None:
            tmux_args += ("-a", allow)

        if deny is not None:
            tmux_args += ("-d", deny)

        if list_access:
            tmux_args += ("-l",)

        proc = self.cmd("server-access", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

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

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

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

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

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

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def start_server(self) -> None:
        """Start the tmux server if not already running.

        Wraps ``$ tmux start-server``. Usually not needed since the server
        starts automatically on first session creation.

        Examples
        --------
        >>> server.start_server()
        """
        proc = self.cmd("start-server")

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def show_messages(self) -> list[str]:
        """Show server message log via ``$ tmux show-messages``.

        Returns
        -------
        list[str]
            Server message log lines.

        Examples
        --------
        >>> result = server.show_messages()
        >>> isinstance(result, list)
        True
        """
        proc = self.cmd("show-messages")

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        return proc.stdout

    def show_prompt_history(
        self,
        *,
        prompt_type: str | None = None,
    ) -> list[str]:
        """Show prompt history via ``$ tmux show-prompt-history``.

        Parameters
        ----------
        prompt_type : str, optional
            Prompt type to show (``-T`` flag). One of: ``command``,
            ``search``, ``target``, ``window-target``.

        Returns
        -------
        list[str]
            Prompt history lines.

        Examples
        --------
        >>> result = server.show_prompt_history()
        >>> isinstance(result, list)
        True
        """
        tmux_args: tuple[str, ...] = ()

        if prompt_type is not None:
            tmux_args += ("-T", prompt_type)

        proc = self.cmd("show-prompt-history", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        return proc.stdout

    def clear_prompt_history(
        self,
        *,
        prompt_type: str | None = None,
    ) -> None:
        """Clear prompt history via ``$ tmux clear-prompt-history``.

        Parameters
        ----------
        prompt_type : str, optional
            Prompt type to clear (``-T`` flag). One of: ``command``,
            ``search``, ``target``, ``window-target``.

        Examples
        --------
        >>> server.clear_prompt_history()
        """
        tmux_args: tuple[str, ...] = ()

        if prompt_type is not None:
            tmux_args += ("-T", prompt_type)

        proc = self.cmd("clear-prompt-history", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

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

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

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

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

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

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

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

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

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

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def list_buffers(self) -> list[str]:
        """List paste buffers via ``$ tmux list-buffers``.

        Returns
        -------
        list[str]
            Raw output lines from list-buffers.

        Examples
        --------
        >>> server.set_buffer('buf_data')
        >>> result = server.list_buffers()
        >>> len(result) >= 1
        True
        """
        proc = self.cmd("list-buffers")

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

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

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

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

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

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

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

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

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

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

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

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
        config_file: StrPath | None = None,
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

            .. versionadded:: 0.45
        no_size : bool, optional
            Do not set the initial window size (``-X`` flag).

            .. versionadded:: 0.45
        config_file : str or PathLike, optional
            Specify an alternative configuration file (``-f`` flag).

            .. versionadded:: 0.45

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
                    if proc.stderr:
                        raise exc.LibTmuxException(proc.stderr)
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
            _fields, format_string = get_output_format()

            tmux_args: tuple[str | int, ...] = (
                "-P",
                f"-F{format_string}",
            )

            if detach_others:
                tmux_args += ("-D",)

            if no_size:
                tmux_args += ("-X",)

            if config_file is not None:
                tmux_args += ("-f", str(pathlib.Path(config_file).expanduser()))

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

            if proc.stderr:
                raise exc.LibTmuxException(proc.stderr)

            session_stdout = proc.stdout[0]

        finally:
            if env:
                os.environ["TMUX"] = env

        session_data = parse_output(session_stdout)

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
        """
        sessions: list[Session] = []

        try:
            for obj in fetch_objs(
                list_cmd="list-sessions",
                server=self,
            ):
                sessions.append(Session(server=self, **obj))  # noqa: PERF401
        except Exception:
            pass

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
            for obj in fetch_objs(
                list_cmd="list-windows",
                list_extra_args=("-a",),
                server=self,
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
            for obj in fetch_objs(
                list_cmd="list-panes",
                list_extra_args=("-a",),
                server=self,
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
