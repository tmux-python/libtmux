# flake8: NOQA: W605
"""Pythonization of the :ref:`tmux(1)` pane.

libtmux.pane
~~~~~~~~~~~~

"""
import dataclasses
import logging
import typing as t
import warnings
from typing import overload

from libtmux.common import tmux_cmd
from libtmux.neo import Obj, fetch_obj

from . import exc

if t.TYPE_CHECKING:
    from .server import Server
    from .session import Session
    from .window import Window


logger = logging.getLogger(__name__)


@dataclasses.dataclass()
class Pane(Obj):
    """:term:`tmux(1)` :term:`Pane` [pane_manual]_.

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

    server: "Server"

    def refresh(self) -> None:
        """Refresh pane attributes from tmux."""
        assert isinstance(self.pane_id, str)
        return super()._refresh(obj_key="pane_id", obj_id=self.pane_id)

    @classmethod
    def from_pane_id(cls, server: "Server", pane_id: str) -> "Pane":
        """Create Pane from existing pane_id."""
        pane = fetch_obj(
            obj_key="pane_id",
            obj_id=pane_id,
            server=server,
            list_cmd="list-panes",
            list_extra_args=("-a",),
        )
        return cls(server=server, **pane)

    #
    # Relations
    #
    @property
    def window(self) -> "Window":
        """Parent window of pane."""
        assert isinstance(self.window_id, str)
        from libtmux.window import Window

        return Window.from_window_id(server=self.server, window_id=self.window_id)

    @property
    def session(self) -> "Session":
        """Parent session of pane."""
        return self.window.session

    """
    Commands (pane-scoped)
    """

    def cmd(self, cmd: str, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        """Execute tmux subcommand against target pane. See also: :meth:`Server.cmd`.

        Send command to tmux with :attr:`pane_id` as ``target-pane``.

        Specifying ``('-t', 'custom-target')`` or ``('-tcustom_target')`` in
        ``args`` will override using the object's ``pane_id`` as target.
        """
        if not any(arg.startswith("-t") for arg in args):
            args = ("-t", self.pane_id, *args)

        return self.server.cmd(cmd, *args, **kwargs)

    """
    Commands (tmux-like)
    """

    def resize_pane(self, *args: t.Any, **kwargs: t.Any) -> "Pane":
        """Resize tmux pane.

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

        self.refresh()
        return self

    def capture_pane(
        self,
        start: t.Union["t.Literal['-']", t.Optional[int]] = None,
        end: t.Union["t.Literal['-']", t.Optional[int]] = None,
    ) -> t.Union[str, t.List[str]]:
        """Capture text from pane.

        ``$ tmux capture-pane`` to pane.
        ``$ tmux capture-pane -S -10`` to pane.
        ``$ tmux capture-pane`-E 3` to pane.
        ``$ tmux capture-pane`-S - -E -` to pane.

        Parameters
        ----------
        start: [str,int]
            Specify the starting line number.
            Zero is the first line of the visible pane.
            Positive numbers are lines in the visible pane.
            Negative numbers are lines in the history.
            `-` is the start of the history.
            Default: None
        end: [str,int]
            Specify the ending line number.
            Zero is the first line of the visible pane.
            Positive numbers are lines in the visible pane.
            Negative numbers are lines in the history.
            `-` is the end of the visible pane
            Default: None
        """
        cmd = ["capture-pane", "-p"]
        if start is not None:
            cmd.extend(["-S", str(start)])
        if end is not None:
            cmd.extend(["-E", str(end)])
        return self.cmd(*cmd).stdout

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
        self,
        cmd: str,
        get_text: "t.Literal[True]",
    ) -> t.Union[str, t.List[str]]:
        ...

    @overload
    def display_message(self, cmd: str, get_text: "t.Literal[False]") -> None:
        ...

    def display_message(
        self,
        cmd: str,
        get_text: bool = False,
    ) -> t.Optional[t.Union[str, t.List[str]]]:
        """Display message to pane.

        Displays a message in target-client status line.

        Parameters
        ----------
        cmd : str
            Special parameters to request from pane.
        get_text : bool, optional
            Returns only text without displaying a message in
            target-client status line.
        """
        if get_text:
            return self.cmd("display-message", "-p", cmd).stdout

        self.cmd("display-message", cmd)
        return None

    """
    Commands ("climber"-helpers)

    These are commands that climb to the parent scope's methods with
    additional scoped window info.
    """

    def select_pane(self) -> "Pane":
        """Select pane.

        To select a window object asynchrously. If a ``pane`` object exists
        and is no longer longer the current window, ``w.select_pane()``
        will make ``p`` the current pane.
        """
        assert isinstance(self.pane_id, str)
        pane = self.window.select_pane(self.pane_id)
        if pane is None:
            raise exc.PaneNotFound(pane_id=self.pane_id)
        return pane

    def split_window(
        self,
        attach: bool = False,
        vertical: bool = True,
        start_directory: t.Optional[str] = None,
        percent: t.Optional[int] = None,
    ) -> "Pane":  # New Pane, not self
        """Split window at pane and return newly created :class:`Pane`.

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
        """
        return self.window.split_window(
            target=self.pane_id,
            start_directory=start_directory,
            attach=attach,
            vertical=vertical,
            percent=percent,
        )

    """
    Commands (helpers)
    """

    def set_width(self, width: int) -> "Pane":
        """Set pane width.

        Parameters
        ----------
        width : int
            pane width, in cells
        """
        self.resize_pane(width=width)
        return self

    def set_height(self, height: int) -> "Pane":
        """Set pane height.

        Parameters
        ----------
        height : int
            height of pain, in cells
        """
        self.resize_pane(height=height)
        return self

    def enter(self) -> "Pane":
        """Send carriage return to pane.

        ``$ tmux send-keys`` send Enter to the pane.
        """
        self.cmd("send-keys", "Enter")
        return self

    def clear(self) -> "Pane":
        """Clear pane."""
        self.send_keys("reset")
        return self

    def reset(self) -> "Pane":
        """Reset and clear pane history."""
        self.cmd("send-keys", r"-R \; clear-history")
        return self

    #
    # Dunder
    #
    def __eq__(self, other: object) -> bool:
        """Equal operator for :class:`Pane` object."""
        if isinstance(other, Pane):
            return self.pane_id == other.pane_id
        return False

    def __repr__(self) -> str:
        """Representation of :class:`Pane` object."""
        return f"{self.__class__.__name__}({self.pane_id} {self.window})"

    #
    # Aliases
    #
    @property
    def id(self) -> t.Optional[str]:
        """Alias of :attr:`Pane.pane_id`.

        >>> pane.id
        '%1'

        >>> pane.id == pane.pane_id
        True
        """
        return self.pane_id

    @property
    def index(self) -> t.Optional[str]:
        """Alias of :attr:`Pane.pane_index`.

        >>> pane.index
        '0'

        >>> pane.index == pane.pane_index
        True
        """
        return self.pane_index

    @property
    def height(self) -> t.Optional[str]:
        """Alias of :attr:`Pane.pane_height`.

        >>> pane.height.isdigit()
        True

        >>> pane.height == pane.pane_height
        True
        """
        return self.pane_height

    @property
    def width(self) -> t.Optional[str]:
        """Alias of :attr:`Pane.pane_width`.

        >>> pane.width.isdigit()
        True

        >>> pane.width == pane.pane_width
        True
        """
        return self.pane_width

    #
    # Legacy: Redundant stuff we want to remove
    #
    def get(self, key: str, default: t.Optional[t.Any] = None) -> t.Any:
        """Return key-based lookup. Deprecated by attributes.

        .. deprecated:: 0.16

           Deprecated by attribute lookup.e.g. ``pane['window_name']`` is now
           accessed via ``pane.window_name``.

        """
        warnings.warn("Pane.get() is deprecated", stacklevel=2)
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> t.Any:
        """Return item lookup by key. Deprecated in favor of attributes.

        .. deprecated:: 0.16

           Deprecated in favor of attributes. e.g. ``pane['window_name']`` is now
           accessed via ``pane.window_name``.

        """
        warnings.warn(f"Item lookups, e.g. pane['{key}'] is deprecated", stacklevel=2)
        return getattr(self, key)
