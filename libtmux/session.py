"""Pythonization of the :term:`tmux(1)` session.

libtmux.session
~~~~~~~~~~~~~~~

"""
import logging
import os

from . import exc, formats
from .common import (
    EnvironmentMixin,
    TmuxMappingObject,
    TmuxRelationalObject,
    handle_option_error,
    has_version,
    session_check_name,
)
from .window import Window

logger = logging.getLogger(__name__)


class Session(TmuxMappingObject, TmuxRelationalObject, EnvironmentMixin):
    """
    A :term:`tmux(1)` :term:`Session` [session_manual]_.

    Holds :class:`Window` objects.

    Parameters
    ----------
    server : :class:`Server`

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

    #: unique child ID key for :class:`~libtmux.common.TmuxRelationalObject`
    child_id_attribute = "window_id"
    #: namespace used :class:`~libtmux.common.TmuxMappingObject`
    formatter_prefix = "session_"

    def __init__(self, server=None, **kwargs):
        EnvironmentMixin.__init__(self)
        self.server = server

        if "session_id" not in kwargs:
            raise ValueError("Session requires a `session_id`")
        self._session_id = kwargs["session_id"]
        self.server._update_windows()

    @property
    def _info(self):

        attrs = {"session_id": str(self._session_id)}

        def by(val):
            for key, value in attrs.items():
                try:
                    if attrs[key] != val[key]:
                        return False
                except KeyError:
                    return False
                return True

        try:
            return list(filter(by, self.server._sessions))[0]
        except IndexError as e:
            logger.error(e)

    def cmd(self, *args, **kwargs):
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
            new_args = [args[0]]
            new_args += ["-t", self.id]
            new_args += args[1:]
            args = new_args
        return self.server.cmd(*args, **kwargs)

    def attach_session(self):
        """Return ``$ tmux attach-session`` aka alias: ``$ tmux attach``."""
        proc = self.cmd("attach-session", "-t%s" % self.id)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def kill_session(self):
        """``$ tmux kill-session``."""

        proc = self.cmd("kill-session", "-t%s" % self.id)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def switch_client(self):
        """
        Switch client to this session.

        Raises
        ------

        :exc:`exc.LibTmuxException`
        """
        proc = self.cmd("switch-client", "-t%s" % self.id)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def rename_session(self, new_name):
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
        window_name=None,
        start_directory=None,
        attach=True,
        window_index="",
        window_shell=None,
    ):
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
        window_shell : str
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
        wformats = ["session_name", "session_id"] + formats.WINDOW_FORMATS
        tmux_formats = ["#{%s}" % f for f in wformats]

        window_args = tuple()

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
        if window_name:
            window_args += ("-n%s" % window_name,)

        window_args += (
            # empty string for window_index will use the first one available
            "-t%s:%s"
            % (self.id, window_index),
        )

        if window_shell:
            window_args += (window_shell,)

        proc = self.cmd("new-window", *window_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        window = proc.stdout[0]

        window = dict(zip(wformats, window.split(formats.FORMAT_SEPARATOR)))

        # clear up empty dict
        window = {k: v for k, v in window.items() if v}
        window = Window(session=self, **window)

        self.server._update_windows()

        return window

    def kill_window(self, target_window=None):
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

    def _list_windows(self):
        windows = self.server._update_windows()._windows

        windows = [w for w in windows if w["session_id"] == self.id]

        return windows

    @property
    def _windows(self):
        """Property / alias to return :meth:`Session._list_windows`."""

        return self._list_windows()

    def list_windows(self):
        """Return a list of :class:`Window` from the ``tmux(1)`` session.

        Returns
        -------
        :class:`Window`
        """
        windows = [w for w in self._windows if w["session_id"] == self._session_id]

        return [Window(session=self, **window) for window in windows]

    @property
    def windows(self):
        """Property / alias to return :meth:`Session.list_windows`."""
        return self.list_windows()

    #: Alias :attr:`windows` for :class:`~libtmux.common.TmuxRelationalObject`
    children = windows

    @property
    def attached_window(self):
        """
        Return active :class:`Window` object.

        Returns
        -------
        :class:`Window`
        """
        active_windows = []
        for window in self._windows:
            if "window_active" in window:
                # for now window_active is a unicode
                if window.get("window_active") == "1":
                    active_windows.append(Window(session=self, **window))
                else:
                    continue

        if len(active_windows) == int(1):
            return active_windows[0]
        else:
            raise exc.LibTmuxException(
                "multiple active windows found. %s" % active_windows
            )

        if len(self._windows) == int(0):
            raise exc.LibTmuxException("No Windows")

    def select_window(self, target_window):
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
    def attached_pane(self):
        """Return active :class:`Pane` object."""

        return self.attached_window.attached_pane

    def set_option(self, option, value, _global=False):
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

        tmux_args = tuple()

        if _global:
            tmux_args += ("-g",)

        tmux_args += (option, value)

        proc = self.cmd("set-option", *tmux_args)

        if isinstance(proc.stderr, list) and len(proc.stderr):
            handle_option_error(proc.stderr[0])

    def show_options(self, option=None, _global=False):
        """
        Return a dict of options for the window.

        For familiarity with tmux, the option ``option`` param forwards to pick
        a single option, forwarding to :meth:`Session.show_option`.

        Parameters
        ----------
        option : str, optional
            name of option, e.g. 'visual-silence'. Defaults to None, which
            returns all options.
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
        tmux_args = tuple()

        if _global:
            tmux_args += ("-g",)

        if option:
            return self.show_option(option, _global=_global)
        else:
            tmux_args += ("show-options",)
            session_options = self.cmd(*tmux_args).stdout

        session_options = [tuple(item.split(" ")) for item in session_options]

        session_options = dict(session_options)

        for key, value in session_options.items():
            if value.isdigit():
                session_options[key] = int(value)

        return session_options

    def show_option(self, option, _global=False):
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

        tmux_args = tuple()

        if _global:
            tmux_args += ("-g",)

        tmux_args += (option,)

        cmd = self.cmd("show-options", *tmux_args)

        if isinstance(cmd.stderr, list) and len(cmd.stderr):
            handle_option_error(cmd.stderr[0])

        if not len(cmd.stdout):
            return None

        option = [item.split(" ") for item in cmd.stdout][0]

        if option[1].isdigit():
            option = (option[0], int(option[1]))

        return option[1]

    def __repr__(self):
        return f"{self.__class__.__name__}({self.id} {self.name})"
