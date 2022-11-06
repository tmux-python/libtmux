"""Pythonization of the :term:`tmux(1)` window.

libtmux.window
~~~~~~~~~~~~~~

"""
import logging
import os
import shlex
import typing as t

from libtmux.common import has_gte_version, tmux_cmd
from libtmux.pane import Pane

from . import exc, formats
from .common import (
    PaneDict,
    TmuxMappingObject,
    TmuxRelationalObject,
    WindowDict,
    WindowOptionDict,
    handle_option_error,
)

if t.TYPE_CHECKING:
    from .server import Server
    from .session import Session

logger = logging.getLogger(__name__)


class Window(TmuxMappingObject, TmuxRelationalObject["Pane", "PaneDict"]):
    """
    A :term:`tmux(1)` :term:`Window` [window_manual]_.

    Holds :class:`Pane` objects.

    Parameters
    ----------
    session : :class:`Session`

    Examples
    --------
    >>> window = session.new_window('My project')

    >>> window
    Window(@2 2:My project, Session($... ...))

    Windows have panes:

    >>> window.panes
    [Pane(...)]

    >>> window.attached_pane
    Pane(...)

    Relations moving up:

    >>> window.session
    Session(...)

    >>> window == session.attached_window
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

    child_id_attribute = "pane_id"
    """Unique child ID key for :class:`~libtmux.common.TmuxRelationalObject`"""
    formatter_prefix = "window_"
    """Namespace used for :class:`~libtmux.common.TmuxMappingObject`"""
    server: "Server"
    """:class:`libtmux.Server` window is linked to"""
    session: "Session"
    """:class:`libtmux.Session` window is linked to"""

    def __init__(
        self, session: "Session", window_id: t.Union[int, str], **kwargs: t.Any
    ) -> None:
        self.session = session
        self.server = self.session.server

        self._window_id = window_id

    def __repr__(self) -> str:
        return "{}({} {}:{}, {})".format(
            self.__class__.__name__,
            self.id,
            self.index,
            self.name,
            self.session,
        )

    @property
    def _info(self) -> WindowDict:  # type: ignore  # mypy#1362
        attrs = {"window_id": self._window_id}

        # from https://github.com/serkanyersen/underscore.py
        def by(val: WindowDict) -> bool:
            for key in attrs.keys():
                try:
                    if attrs[key] != val[key]:
                        return False
                except KeyError:
                    return False
            return True

        target_windows = [s for s in self.server._windows if by(s)]
        # If a window_shell option was configured which results in
        # a short-lived process, the window id is @0.  Use that instead of
        # self._window_id
        if len(target_windows) == 0 and self.server._windows[0]["window_id"] == "@0":
            target_windows = self.server._windows
        return target_windows[0]

    def cmd(self, cmd: str, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        """Return :meth:`Server.cmd` defaulting ``target_window`` as target.

        Send command to tmux with :attr:`window_id` as ``target-window``.

        Specifying ``('-t', 'custom-target')`` or ``('-tcustom_target')`` in
        ``args`` will override using the object's ``window_id`` as target.

        Returns
        -------
        :class:`Server.cmd`

        Notes
        -----
        .. versionchanged:: 0.8

            Renamed from ``.tmux`` to ``.cmd``.
        """
        if not any(arg.startswith("-t") for arg in args):
            args = ("-t", self.id) + args

        return self.server.cmd(cmd, *args, **kwargs)

    def select_layout(self, layout: t.Optional[str] = None) -> None:
        """Wrapper for ``$ tmux select-layout <layout>``.

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
        cmd = ["select-layout", "-t{}:{}".format(self.get("session_id"), self.index)]

        if layout:  # tmux allows select-layout without args
            cmd.append(layout)

        proc = self.cmd(*cmd)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def set_window_option(self, option: str, value: t.Union[int, str]) -> None:
        """
        Wrapper for ``$ tmux set-window-option <option> <value>``.

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

        self.server._update_windows()

        if isinstance(value, bool) and value:
            value = "on"
        elif isinstance(value, bool) and not value:
            value = "off"

        cmd = self.cmd(
            "set-window-option",
            "-t{}:{}".format(self.get("session_id"), self.index),
            # '-t%s' % self.id,
            option,
            value,
        )

        if isinstance(cmd.stderr, list) and len(cmd.stderr):
            handle_option_error(cmd.stderr[0])

    def show_window_options(self, g: t.Optional[bool] = False) -> WindowOptionDict:
        """
        Return a dict of options for the window.

        For familiarity with tmux, the option ``option`` param forwards to
        pick a single option, forwarding to :meth:`Window.show_window_option`.

        .. versionchanged:: 0.13.0

           ``option`` removed, use show_window_option to return an individual option.

        Parameters
        ----------
        g : str, optional
            Pass ``-g`` flag for global variable, default False.

        Returns
        -------
        dict
        """
        tmux_args: t.Tuple[str, ...] = tuple()

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
            key, val = shlex.split(item)
            assert isinstance(key, str)
            assert isinstance(val, str)

            if isinstance(val, str) and val.isdigit():
                window_options[key] = int(val)

        return window_options

    def show_window_option(
        self, option: str, g: bool = False
    ) -> t.Optional[t.Union[str, int]]:
        """
        Return a list of options for the window.

        todo: test and return True/False for on/off string

        Parameters
        ----------
        option : str
        g : bool, optional
            Pass ``-g`` flag, global. Default False.

        Returns
        -------
        str, int

        Raises
        ------
        :exc:`exc.OptionError`, :exc:`exc.UnknownOption`,
        :exc:`exc.InvalidOption`, :exc:`exc.AmbiguousOption`
        """
        tmux_args: t.Tuple[t.Union[str, int], ...] = tuple()

        if g:
            tmux_args += ("-g",)

        tmux_args += (option,)

        cmd = self.cmd("show-window-options", *tmux_args)

        if len(cmd.stderr):
            handle_option_error(cmd.stderr[0])

        window_options_output = cmd.stdout

        if not len(window_options_output):
            return None

        value_raw = [shlex.split(item) for item in window_options_output][0]

        value: t.Union[str, int] = (
            int(value_raw[1]) if value_raw[1].isdigit() else value_raw[1]
        )

        return value

    def rename_window(self, new_name: str) -> "Window":
        """
        Return :class:`Window` object ``$ tmux rename-window <new_name>``.

        Parameters
        ----------
        new_name : str
            name of the window

        Examples
        --------

        >>> window = session.attached_window

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
            self["window_name"] = new_name
        except Exception as e:
            logger.error(e)

        self.server._update_windows()

        return self

    def kill_window(self) -> None:
        """Kill the current :class:`Window` object. ``$ tmux kill-window``."""

        proc = self.cmd(
            "kill-window",
            # '-t:%s' % self.id
            "-t{}:{}".format(self.get("session_id"), self.index),
        )

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        self.server._update_windows()

    def move_window(
        self, destination: str = "", session: t.Optional[str] = None
    ) -> None:
        """
        Move the current :class:`Window` object ``$ tmux move-window``.

        Parameters
        ----------
        destination : str, optional
            the ``target window`` or index to move the window to, default:
            empty string
        session : str, optional
            the ``target session`` or index to move the window to, default:
            current session.
        """
        session = session or self.get("session_id")
        proc = self.cmd(
            "move-window",
            "-s{}:{}".format(self.get("session_id"), self.index),
            f"-t{session}:{destination}",
        )

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        self.server._update_windows()

    def select_window(self) -> "Window":
        """
        Select window. Return ``self``.

        To select a window object asynchrously. If a ``window`` object exists
        and is no longer longer the current window, ``w.select_window()``
        will make ``w`` the current window.

        Returns
        -------
        :class:`Window`
        """
        return self.session.select_window(self.index)

    def select_pane(self, target_pane: t.Union[str, int]) -> t.Optional[Pane]:
        """
        Return selected :class:`Pane` through ``$ tmux select-pane``.

        Parameters
        ----------
        target_pane : str
            'target_pane', '-U' ,'-D', '-L', '-R', or '-l'.

        Return
        ------
        :class:`Pane`
        """

        if target_pane in ["-l", "-U", "-D", "-L", "-R"]:
            proc = self.cmd("select-pane", "-t%s" % self.id, target_pane)
        else:
            proc = self.cmd("select-pane", "-t%s" % target_pane)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        return self.attached_pane

    def last_pane(self) -> t.Optional[Pane]:
        """Return last pane."""
        return self.select_pane("-l")

    def split_window(
        self,
        target: t.Optional[t.Union[int, str]] = None,
        start_directory: t.Optional[str] = None,
        attach: bool = True,
        vertical: bool = True,
        shell: t.Optional[str] = None,
        percent: t.Optional[int] = None,
        environment: t.Optional[t.Dict[str, str]] = None,
    ) -> Pane:
        """
        Split window and return the created :class:`Pane`.

        Used for splitting window and holding in a python object.

        Parameters
        ----------
        attach : bool, optional
            make new window the current window after creating it, default
            True.
        start_directory : str, optional
            specifies the working directory in which the new window is created.
        target : str
            ``target_pane`` to split.
        vertical : str
            split vertically
        shell : str, optional
            execute a command on splitting the window.  The pane will close
            when the command exits.

            NOTE: When this command exits the pane will close.  This feature
            is useful for long-running processes where the closing of the
            window upon completion is desired.
        percent: int, optional
            percentage to occupy with respect to current window
        environment: dict, optional
            Environmental variables for new pane. tmux 3.0+ only. Passthrough to ``-e``.

        Returns
        -------
        :class:`Pane`

        Notes
        -----

        :term:`tmux(1)` will move window to the new pane if the
        ``split-window`` target is off screen. tmux handles the ``-d`` the
        same way as ``new-window`` and ``attach`` in
        :class:`Session.new_window`.

        By default, this will make the window the pane is created in
        active. To remain on the same window and split the pane in another
        target window, pass in ``attach=False``.
        """
        pformats = [
            "session_name",
            "session_id",
            "window_index",
            "window_id",
        ] + formats.PANE_FORMATS
        tmux_formats = [(f"#{{{f}}}{formats.FORMAT_SEPARATOR}") for f in pformats]

        # '-t%s' % self.attached_pane.get('pane_id'),
        # 2013-10-18 LOOK AT THIS, rm'd it..
        tmux_args: t.Tuple[str, ...] = tuple()

        if target:
            tmux_args += ("-t%s" % target,)
        else:
            tmux_args += ("-t%s" % self.panes[0].get("pane_id"),)

        if vertical:
            tmux_args += ("-v",)
        else:
            tmux_args += ("-h",)

        if percent is not None:
            tmux_args += ("-p %d" % percent,)

        tmux_args += ("-P", "-F%s" % "".join(tmux_formats))  # output

        if start_directory:
            # as of 2014-02-08 tmux 1.9-dev doesn't expand ~ in new-window -c.
            start_directory = os.path.expanduser(start_directory)
            tmux_args += ("-c%s" % start_directory,)

        if not attach:
            tmux_args += ("-d",)

        if environment:
            if has_gte_version("3.0"):
                for k, v in environment.items():
                    tmux_args += (f"-e{k}={v}",)
            else:
                logger.warning(
                    "Cannot set up environment as tmux 3.0 or newer is required."
                )

        if shell:
            tmux_args += (shell,)

        pane_cmd = self.cmd("split-window", *tmux_args)

        # tmux < 1.7. This is added in 1.7.
        if pane_cmd.stderr:
            if "pane too small" in pane_cmd.stderr:
                raise exc.LibTmuxException(pane_cmd.stderr)

            raise exc.LibTmuxException(pane_cmd.stderr, self._info, self.panes)

        pane_output = pane_cmd.stdout[0]

        pane_formatters = dict(
            zip(pformats, pane_output.split(formats.FORMAT_SEPARATOR))
        )

        # Prune empty values
        pane_formatters_filtered = {k: v for k, v in pane_formatters.items() if v}

        return Pane(window=self, **pane_formatters_filtered)

    @property
    def attached_pane(self) -> t.Optional[Pane]:
        """
        Return the attached :class:`Pane`.

        Returns
        -------
        :class:`Pane`
        """
        for pane in self._panes:
            # for now pane_active is a unicode
            if "pane_active" in pane and pane.get("pane_active") == "1":
                return Pane(window=self, **pane)
        return None

    def _list_panes(self) -> t.List[PaneDict]:
        panes = self.server._update_panes()._panes

        panes = [p for p in panes if p["session_id"] == self.get("session_id")]
        panes = [p for p in panes if p["window_id"] == self.id]
        return panes

    @property
    def _panes(self) -> t.List[PaneDict]:
        """Property / alias to return :meth:`~._list_panes`."""

        return self._list_panes()

    def list_panes(self) -> t.List[Pane]:
        """
        Return list of :class:`Pane` for the window.

        Returns
        -------
        list of :class:`Pane`
        """

        return [Pane(window=self, **pane) for pane in self._panes]

    @property
    def panes(self) -> t.List[Pane]:
        """Property / alias to return :meth:`~.list_panes`."""
        return self.list_panes()

    #: Alias :attr:`panes` for :class:`~libtmux.common.TmuxRelationalObject`
    children = panes  # type:ignore  # mypy#1362
