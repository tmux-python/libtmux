# flake8: NOQA W605
"""Pythonization of the :ref:`tmux(1)` pane.

libtmux.pane
~~~~~~~~~~~~

"""
from __future__ import annotations

import dataclasses
import logging
import typing as t
from typing import overload

import libtmux
from libtmux.common import tmux_cmd

from . import exc
from .common import PaneDict, TmuxMappingObject

if t.TYPE_CHECKING:
    from typing_extensions import Literal

    from .server import Server
    from .session import Session
    from .window import Window


logger = logging.getLogger(__name__)

__all__ = ["Pane"]


@dataclasses.dataclass
class Pane(TmuxMappingObject):
    """
    A :term:`tmux(1)` :term:`Pane` [pane_manual]_.

    ``Pane`` instances can send commands directly to a pane, or traverse
    between linked tmux objects.

    Attributes
    ----------
    window : :class:`Window`

    Examples
    --------
    >>> pane
    Pane(%1 Window(@1 1:..., Session($1 ...)))

    >>> pane in window.panes
    True

    >>> pane.window
    Window(@1 1:..., Session($1 ...))

    >>> pane.session
    Session($1 ...)

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

    window: libtmux.window.Window
    session_name: str = dataclasses.field(init=True)
    session_id: str = dataclasses.field(init=True)
    window_index: str = dataclasses.field(init=True)
    window_id: str = dataclasses.field(init=True)
    history_size: str
    history_limit: str
    history_bytes: str
    pane_index: str
    pane_width: str
    pane_height: str
    pane_title: str
    _pane_id: str = dataclasses.field(init=False)  # Legacy, relational
    pane_id: str
    pane_active: str
    pane_dead: str
    pane_in_mode: str
    pane_synchronized: str
    pane_tty: str
    pane_pid: str
    pane_current_path: str
    pane_current_command: str
    cursor_x: str
    cursor_y: str
    scroll_region_upper: str
    scroll_region_lower: str
    alternate_on: str
    alternate_saved_x: str
    alternate_saved_y: str
    cursor_flag: str
    insert_flag: str
    keypad_cursor_flag: str
    keypad_flag: str
    wrap_flag: str
    mouse_standard_flag: str
    mouse_button_flag: str
    mouse_any_flag: str
    mouse_utf8_flag: str
    session: libtmux.session.Session = dataclasses.field(init=False)
    server: libtmux.server.Server = dataclasses.field(init=False)
    window_name: str = dataclasses.field(init=True, default="")
    pane_start_command: t.Optional[str] = dataclasses.field(init=True, default=None)

    formatter_prefix = "pane_"
    """Namespace used for :class:`~libtmux.common.TmuxMappingObject`"""

    def __post_init__(self, **kwargs: t.Any) -> None:
        # if not window:
        #     raise ValueError("Pane must have ``Window`` object")
        #
        # self.window = window
        self.session = self.window.session
        self.server = self.session.server

        self._pane_id = self.pane_id

        try:
            info = self._info
        except IndexError:
            info = {}
        for k, v in info.items():
            if not hasattr(k, v):
                setattr(self, k, v)

        self.server._update_panes()

    def refresh(self) -> None:
        try:
            info = self._info
        except IndexError:
            info = {}
        for k, v in info.items():
            if not hasattr(k, v):
                setattr(self, k, v)

    @property
    def _info(self) -> PaneDict:  # type: ignore  # mypy#1362
        # attrs = {"pane_id": self._pane_id}
        attrs = {"pane_id": object.__getattribute__(self, "_pane_id")}

        # from https://github.com/serkanyersen/underscore.py
        def by(val: PaneDict) -> bool:
            for key in attrs.keys():
                try:
                    if attrs[key] != val[key]:
                        return False
                except KeyError:
                    return False
            return True

        target_panes = [s for s in self.server._panes if by(s)]

        return target_panes[0]

    def cmd(self, cmd: str, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
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

    def send_keys(
        self,
        cmd: str,
        enter: t.Optional[bool] = True,
        suppress_history: t.Optional[bool] = False,
        literal: t.Optional[bool] = False,
    ) -> None:
        r"""``$ tmux send-keys`` to the pane.

        A leading space character is added to cmd to avoid polluting the
        user's history.

        Parameters
        ----------
        cmd : str
            Text or input into pane
        enter : bool, optional
            Send enter after sending the input, default True.
        suppress_history : bool, optional
            Prepend a space to command to suppress shell history, default False.

            .. versionchanged:: 0.14

               Default changed from True to False.
        literal : bool, optional
            Send keys literally, default True.

        Examples
        --------
        >>> pane = window.split_window(shell='sh')
        >>> pane.capture_pane()
        ['$']

        >>> pane.send_keys('echo "Hello world"', enter=True)

        >>> pane.capture_pane()
        ['$ echo "Hello world"', 'Hello world', '$']

        >>> print('\n'.join(pane.capture_pane()))  # doctest: +NORMALIZE_WHITESPACE
        $ echo "Hello world"
        Hello world
        $
        """
        prefix = " " if suppress_history else ""

        if literal:
            self.cmd("send-keys", "-l", prefix + cmd)
        else:
            self.cmd("send-keys", prefix + cmd)

        if enter:
            self.enter()

    @overload
    def display_message(
        self, cmd: str, get_text: "Literal[True]"
    ) -> t.Union[str, t.List[str]]:
        ...

    @overload
    def display_message(self, cmd: str, get_text: "Literal[False]") -> None:
        ...

    def display_message(
        self, cmd: str, get_text: bool = False
    ) -> t.Optional[t.Union[str, t.List[str]]]:
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

        self.cmd("display-message", cmd)
        return None

    def clear(self) -> None:
        """Clear pane."""
        self.send_keys("reset")

    def reset(self) -> None:
        """Reset and clear pane history."""

        self.cmd("send-keys", r"-R \; clear-history")

    def split_window(
        self,
        attach: bool = False,
        vertical: bool = True,
        start_directory: t.Optional[str] = None,
        percent: t.Optional[int] = None,
    ) -> "Pane":
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

    def set_width(self, width: int) -> None:
        """
        Set width of pane.

        Parameters
        ----------
        width : int
            pane width, in cells
        """
        self.resize_pane(width=width)

    def set_height(self, height: int) -> None:
        """
        Set height of pane.

        Parameters
        ----------
        height : int
            height of pain, in cells
        """
        self.resize_pane(height=height)

    def resize_pane(self, *args: t.Any, **kwargs: t.Any) -> "Pane":
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
        self.refresh()
        return self

    def enter(self) -> None:
        """
        Send carriage return to pane.

        ``$ tmux send-keys`` send Enter to the pane.
        """
        self.cmd("send-keys", "Enter")

    def capture_pane(self) -> t.Union[str, t.List[str]]:
        """
        Capture text from pane.

        ``$ tmux capture-pane`` to pane.

        Returns
        -------
        :class:`list`
        """
        return self.cmd("capture-pane", "-p").stdout

    def select_pane(self) -> "Pane":
        """
        Select pane. Return ``self``.

        To select a window object asynchrously. If a ``pane`` object exists
        and is no longer longer the current window, ``w.select_pane()``
        will make ``p`` the current pane.

        Returns
        -------
        :class:`pane`
        """
        pane = self.window.select_pane(self._pane_id)
        if pane is None:
            raise exc.LibTmuxException(f"Pane not found: {self}")
        return pane

    def __repr__(self) -> str:
        return "{}({} {})".format(
            self.__class__.__name__, self.get("pane_id"), self.window
        )
