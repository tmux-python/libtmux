"""Pythonization of the :term:`tmux(1)` session.

libtmux.session
~~~~~~~~~~~~~~~

"""
import logging
import os
import typing as t

from libtmux.common import tmux_cmd
from libtmux.window import Window

from . import exc, formats
from .common import (
    EnvironmentMixin,
    SessionDict,
    TmuxMappingObject,
    TmuxRelationalObject,
    WindowDict,
    handle_option_error,
    has_gte_version,
    has_version,
    session_check_name,
)

if t.TYPE_CHECKING:
    from .pane import Pane
    from .server import Server


logger = logging.getLogger(__name__)


class Session(
    TmuxMappingObject, TmuxRelationalObject["Window", "WindowDict"], EnvironmentMixin
):
    """
    A :term:`tmux(1)` :term:`Session` [session_manual]_.

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

    child_id_attribute = "window_id"
    """Unique child ID key for :class:`~libtmux.common.TmuxRelationalObject`"""
    formatter_prefix = "session_"
    """Namespace used for :class:`~libtmux.common.TmuxMappingObject`"""
    server: "Server"
    """:class:`libtmux.server.Server` session is linked to"""

    def __init__(self, server: "Server", session_id: str, **kwargs: t.Any) -> None:
        EnvironmentMixin.__init__(self)
        self.server = server

        self._session_id = session_id
        self.server._update_windows()

    @property
    def _info(self) -> t.Optional[SessionDict]:  # type: ignore  # mypy#1362
        attrs = {"session_id": str(self._session_id)}

        def by(val: SessionDict) -> bool:
            for key in attrs.keys():
                try:
                    if attrs[key] != val[key]:
                        return False
                except KeyError:
                    return False
            return True

        target_sessions = [s for s in self.server._sessions if by(s)]
        try:
            return target_sessions[0]
        except IndexError as e:
            logger.error(e)
        return None

    def cmd(self, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        """
        Return :meth:`server.cmd`.

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
            new_args: t.Tuple[str, ...] = tuple()
            new_args += (args[0],)
            new_args += (
                "-t",
                self.id,
            )
            new_args += tuple(args[1:])
            args = new_args
        return self.server.cmd(*args, **kwargs)

    def attach_session(self) -> None:
        """Return ``$ tmux attach-session`` aka alias: ``$ tmux attach``."""
        proc = self.cmd("attach-session", "-t%s" % self.id)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def kill_session(self) -> None:
        """``$ tmux kill-session``."""

        proc = self.cmd("kill-session", "-t%s" % self.id)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def switch_client(self) -> None:
        """
        Switch client to this session.

        Raises
        ------

        :exc:`exc.LibTmuxException`
        """
        proc = self.cmd("switch-client", "-t%s" % self.id)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def rename_session(self, new_name: str) -> "Session":
        """
        Rename session and return new :class:`Session` object.

        Parameters
        ----------
        new_name : str
            new session name

        Returns
        -------
        :class:`Session`

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

        return self

    def new_window(
        self,
        window_name: t.Optional[str] = None,
        start_directory: None = None,
        attach: bool = True,
        window_index: str = "",
        window_shell: t.Optional[str] = None,
        environment: t.Optional[t.Dict[str, str]] = None,
    ) -> Window:
        """
        Return :class:`Window` from ``$ tmux new-window``.

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
        environment: dict, optional
            Environmental variables for new window. tmux 3.0+ only. Passthrough to
            ``-e``.

        Returns
        -------
        :class:`Window`
        """
        wformats = ["session_name", "session_id"] + formats.WINDOW_FORMATS
        tmux_formats = ["#{%s}" % f for f in wformats]

        window_args: t.Tuple[str, ...] = tuple()

        if not attach:
            window_args += ("-d",)

        window_args += ("-P",)

        if start_directory:
            # as of 2014-02-08 tmux 1.9-dev doesn't expand ~ in new-window -c.
            start_directory = os.path.expanduser(start_directory)
            window_args += ("-c%s" % start_directory,)

        window_args += (
            '-F"%s"' % formats.FORMAT_SEPARATOR.join(tmux_formats),
        )  # output
        if window_name is not None and isinstance(window_name, str):
            window_args += ("-n", window_name)

        window_args += (
            # empty string for window_index will use the first one available
            "-t%s:%s"
            % (self.id, window_index),
        )

        if environment:
            if has_gte_version("3.0"):
                for k, v in environment.items():
                    window_args += (f"-e{k}={v}",)
            else:
                logger.warning(
                    "Cannot set up environment as tmux 3.0 or newer is required."
                )

        if window_shell:
            window_args += (window_shell,)

        cmd = self.cmd("new-window", *window_args)

        if cmd.stderr:
            raise exc.LibTmuxException(cmd.stderr)

        window_output = cmd.stdout[0]

        window_formatters = dict(
            zip(wformats, window_output.split(formats.FORMAT_SEPARATOR))
        )

        # clear up empty dict
        window_formatters_filtered = {k: v for k, v in window_formatters.items() if v}
        window = Window(session=self, **window_formatters_filtered)

        self.server._update_windows()

        return window

    def kill_window(self, target_window: t.Optional[str] = None) -> None:
        """Close a tmux window, and all panes inside it, ``$ tmux kill-window``

        Kill the current window or the window at ``target-window``. removing it
        from any sessions to which it is linked.

        Parameters
        ----------
        target_window : str, optional
            window to kill
        """

        if target_window:
            if isinstance(target_window, int):
                target = "-t%s:%d" % (self.name, target_window)
            else:
                target = "-t%s" % target_window

        proc = self.cmd("kill-window", target)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        self.server._update_windows()

    def _list_windows(self) -> t.List[WindowDict]:
        windows = self.server._update_windows()._windows

        return [w for w in windows if w["session_id"] == self.id]

    @property
    def _windows(self) -> t.List[WindowDict]:
        """Property / alias to return :meth:`Session._list_windows`."""

        return self._list_windows()

    def list_windows(self) -> t.List[Window]:
        """Return a list of :class:`Window` from the ``tmux(1)`` session.

        Returns
        -------
        :class:`Window`
        """
        windows = [w for w in self._windows if w["session_id"] == self._session_id]

        return [Window(session=self, **window) for window in windows]

    @property
    def windows(self) -> t.List[Window]:
        """Property / alias to return :meth:`Session.list_windows`."""
        return self.list_windows()

    #: Alias :attr:`windows` for :class:`~libtmux.common.TmuxRelationalObject`
    children = windows  # type: ignore  # mypy#1362

    @property
    def attached_window(self) -> Window:
        """
        Return active :class:`Window` object.

        Returns
        -------
        :class:`Window`
        """
        active_windows = []
        for window in self._windows:
            # for now window_active is a unicode
            if "window_active" in window and window.get("window_active") == "1":
                active_windows.append(Window(session=self, **window))

        if len(active_windows) == 1:
            return active_windows[0]
        else:
            raise exc.LibTmuxException(
                "multiple active windows found. %s" % active_windows
            )

        if len(self._windows) == 0:
            raise exc.LibTmuxException("No Windows")

    def select_window(self, target_window: t.Union[str, int]) -> Window:
        """
        Return :class:`Window` selected via ``$ tmux select-window``.

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
        target = f"-t{self._session_id}:{target_window}"

        proc = self.cmd("select-window", target)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        return self.attached_window

    @property
    def attached_pane(self) -> t.Optional["Pane"]:
        """Return active :class:`Pane` object."""

        return self.attached_window.attached_pane

    def set_option(
        self, option: str, value: t.Union[str, int], _global: bool = False
    ) -> None:
        """
        Set option ``$ tmux set-option <option> <value>``.

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

        tmux_args: t.Tuple[t.Union[str, int], ...] = tuple()

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

    def show_options(
        self, _global: t.Optional[bool] = False
    ) -> t.Dict[str, t.Union[str, int]]:
        """
        Return a dict of options for the window.

        For familiarity with tmux, the option ``option`` param forwards to pick
        a single option, forwarding to :meth:`Session.show_option`.

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
        tmux_args: t.Tuple[str, ...] = tuple()

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
        self, option: str, _global: bool = False
    ) -> t.Optional[t.Union[str, int, bool]]:
        """Return a list of options for the window.

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

        tmux_args: t.Tuple[str, ...] = tuple()

        if _global:
            tmux_args += ("-g",)

        tmux_args += (option,)

        cmd = self.cmd("show-options", *tmux_args)

        if isinstance(cmd.stderr, list) and len(cmd.stderr):
            handle_option_error(cmd.stderr[0])

        if not len(cmd.stdout):
            return None

        value_raw: t.List[str] = [item.split(" ") for item in cmd.stdout][0]

        assert isinstance(value_raw[0], str)
        assert isinstance(value_raw[1], str)

        value: t.Union[str, int] = (
            int(value_raw[1]) if value_raw[1].isdigit() else value_raw[1]
        )

        return value

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.id} {self.name})"
