# flake8: NOQA W605
"""Pythonization of the :ref:`tmux(1)` pane.

libtmux.pane
~~~~~~~~~~~~

"""
import logging

from . import exc
from .common import TmuxMappingObject, TmuxRelationalObject

logger = logging.getLogger(__name__)


class Pane(TmuxMappingObject, TmuxRelationalObject):
    """
    A :term:`tmux(1)` :term:`Pane` [pane_manual]_.

    ``Pane`` instances can send commands directly to a pane, or traverse
    between linked tmux objects.

    Parameters
    ----------
    window : :class:`Window`

    Notes
    -----

    .. versionchanged:: 0.8
        Renamed from ``.tmux`` to ``.cmd``.

    References
    ----------

    .. [pane_manual] tmux pane. openbsd manpage for TMUX(1).
           "Each window displayed by tmux may be split into one or more
           panes; each pane takes up a certain area of the display and is
           a separate terminal."

       https://man.openbsd.org/tmux.1#WINDOWS_AND_PANES.
       Accessed April 1st, 2018.
    """

    #: namespace used :class:`~libtmux.common.TmuxMappingObject`
    formatter_prefix = "pane_"

    def __init__(self, window=None, **kwargs):
        if not window:
            raise ValueError("Pane must have ``Window`` object")

        self.window = window
        self.session = self.window.session
        self.server = self.session.server

        self._pane_id = kwargs["pane_id"]

        self.server._update_panes()

    @property
    def _info(self, *args):

        attrs = {"pane_id": self._pane_id}

        # from https://github.com/serkanyersen/underscore.py
        def by(val, *args):
            for key, value in attrs.items():
                try:
                    if attrs[key] != val[key]:
                        return False
                except KeyError:
                    return False
                return True

        return list(filter(by, self.server._panes))[0]

    def cmd(self, cmd, *args, **kwargs):
        """Return :meth:`Server.cmd` defaulting to ``target_pane`` as target.

        Send command to tmux with :attr:`pane_id` as ``target-pane``.

        Specifying ``('-t', 'custom-target')`` or ``('-tcustom_target')`` in
        ``args`` will override using the object's ``pane_id`` as target.

        Returns
        -------
        :class:`Server.cmd`
        """
        if not any(arg.startswith("-t") for arg in args):
            args = ("-t", self.get("pane_id")) + args

        return self.server.cmd(cmd, *args, **kwargs)

    def send_keys(self, cmd, enter=True, suppress_history=True, literal=False):
        """
        ``$ tmux send-keys`` to the pane.

        A leading space character is added to cmd to avoid polluting the
        user's history.

        Parameters
        ----------
        cmd : str
            Text or input into pane
        enter : bool, optional
            Send enter after sending the input, default True.
        suppress_history : bool, optional
            Don't add these keys to the shell history, default True.
        literal : bool, optional
            Send keys literally, default True.
        """
        prefix = " " if suppress_history else ""

        if literal:
            self.cmd("send-keys", "-l", prefix + cmd)
        else:
            self.cmd("send-keys", prefix + cmd)

        if enter:
            self.enter()

    def display_message(self, cmd, get_text=False):
        """
        ``$ tmux display-message`` to the pane.

        Displays a message in target-client status line.

        Parameters
        ----------
        cmd : str
            Special parameters to request from pane.
        get_text : bool, optional
            Returns only text without displaying a message in
            target-client status line.

        Returns
        -------
        :class:`list`
        :class:`None`
        """
        if get_text:
            return self.cmd("display-message", "-p", cmd).stdout
        else:
            self.cmd("display-message", cmd)

    def clear(self):
        """Clear pane."""
        self.send_keys("reset")

    def reset(self):
        """Reset and clear pane history."""

        self.cmd("send-keys", r"-R \; clear-history")

    def split_window(
        self, attach=False, vertical=True, start_directory=None, percent=None
    ):
        """
        Split window at pane and return newly created :class:`Pane`.

        Parameters
        ----------
        attach : bool, optional
            Attach / select pane after creation.
        vertical : bool, optional
            split vertically
        start_directory : str, optional
            specifies the working directory in which the new pane is created.
        percent: int, optional
            percentage to occupy with respect to current pane

        Returns
        -------
        :class:`Pane`
        """
        return self.window.split_window(
            target=self.get("pane_id"),
            start_directory=start_directory,
            attach=attach,
            vertical=vertical,
            percent=percent,
        )

    def set_width(self, width):
        """
        Set width of pane.

        Parameters
        ----------
        width : int
            pane width, in cells
        """
        self.resize_pane(width=width)

    def set_height(self, height):
        """
        Set height of pane.

        Parameters
        ----------
        height : int
            height of pain, in cells
        """
        self.resize_pane(height=height)

    def resize_pane(self, *args, **kwargs):
        """
        ``$ tmux resize-pane`` of pane and return ``self``.

        Parameters
        ----------
        target_pane : str
            ``target_pane``, or ``-U``,``-D``, ``-L``, ``-R``.

        Other Parameters
        ----------------
        height : int
            ``resize-pane -y`` dimensions
        width : int
            ``resize-pane -x`` dimensions

        Returns
        -------
        :class:`Pane`

        Raises
        ------
        exc.LibTmuxException
        """

        if "height" in kwargs:
            proc = self.cmd("resize-pane", "-y%s" % int(kwargs["height"]))
        elif "width" in kwargs:
            proc = self.cmd("resize-pane", "-x%s" % int(kwargs["width"]))
        else:
            proc = self.cmd("resize-pane", args[0])

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        self.server._update_panes()
        return self

    def enter(self):
        """
        Send carriage return to pane.

        ``$ tmux send-keys`` send Enter to the pane.
        """
        self.cmd("send-keys", "Enter")

    def capture_pane(self):
        """
        Capture text from pane.

        ``$ tmux capture-pane`` to pane.

        Returns
        -------
        :class:`list`
        """
        return self.cmd("capture-pane", "-p").stdout

    def select_pane(self):
        """
        Select pane. Return ``self``.

        To select a window object asynchrously. If a ``pane`` object exists
        and is no longer longer the current window, ``w.select_pane()``
        will make ``p`` the current pane.

        Returns
        -------
        :class:`pane`
        """
        return self.window.select_pane(self.get("pane_id"))

    def __repr__(self):
        return "{}({} {})".format(
            self.__class__.__name__, self.get("pane_id"), self.window
        )
