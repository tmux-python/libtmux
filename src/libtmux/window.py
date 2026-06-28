"""Pythonization of the :term:`tmux(1)` window.

libtmux.window
~~~~~~~~~~~~~~

"""

from __future__ import annotations

import dataclasses
import logging
import pathlib
import shlex
import typing as t
import warnings

from libtmux._internal.query_list import QueryList
from libtmux.common import has_gte_version, raise_if_stderr, tmux_cmd
from libtmux.constants import (
    RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP,
    OptionScope,
    PaneDirection,
    ResizeAdjustmentDirection,
    WindowDirection,
)
from libtmux.hooks import HooksMixin
from libtmux.neo import Obj, fetch_obj, fetch_objs
from libtmux.pane import Pane

from . import exc
from .common import PaneDict, WindowOptionDict
from .options import OptionsMixin

if t.TYPE_CHECKING:
    import sys
    import types

    from libtmux._internal.types import StrPath

    from .common import PaneDict, WindowOptionDict
    from .server import Server
    from .session import Session

    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing_extensions import Self


logger = logging.getLogger(__name__)


@dataclasses.dataclass()
class Window(
    Obj,
    OptionsMixin,
    HooksMixin,
):
    """:term:`tmux(1)` :term:`Window` [window_manual]_.

    Holds :class:`Pane` objects.

    Parameters
    ----------
    session : :class:`Session`

    Examples
    --------
    >>> window = session.new_window('My project', attach=True)

    >>> window
    Window(@2 2:My project, Session($... ...))

    Windows have panes:

    >>> window.panes
    [Pane(...)]

    >>> window.active_pane
    Pane(...)

    Relations moving up:

    >>> window.session
    Session(...)

    >>> window.window_id == session.active_window.window_id
    True

    >>> window == session.active_window
    True

    >>> window in session.windows
    True

    The window can be used as a context manager to ensure proper cleanup:

    >>> with session.new_window() as window:
    ...     pane = window.split()
    ...     # Do work with the pane
    ...     # Window will be killed automatically when exiting the context

    References
    ----------
    .. [window_manual] tmux window. openbsd manpage for TMUX(1).
           "Each session has one or more windows linked to it. A window
           occupies the entire screen and may be split into rectangular
           panes..."

       https://man.openbsd.org/tmux.1#DESCRIPTION. Accessed April 1st, 2018.
    """

    default_option_scope: OptionScope | None = OptionScope.Window
    default_hook_scope: OptionScope | None = OptionScope.Window
    server: Server

    def __enter__(self) -> Self:
        """Enter the context, returning self.

        Returns
        -------
        :class:`Window`
            The window instance
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Exit the context, killing the window if it exists.

        Parameters
        ----------
        exc_type : type[BaseException] | None
            The type of the exception that was raised
        exc_value : BaseException | None
            The instance of the exception that was raised
        exc_tb : types.TracebackType | None
            The traceback of the exception that was raised
        """
        if (
            self.window_id is not None
            and len(self.session.windows.filter(window_id=self.window_id)) > 0
        ):
            self.kill()

    def refresh(self) -> None:
        """Refresh window attributes from tmux.

        Raises
        ------
        ValueError
            When ``window_id`` is unset. Surfaces a clear error under
            ``python -O``, where an ``assert`` would be stripped.
        """
        if self.window_id is None:
            msg = "Window must have a window_id to refresh"
            raise ValueError(msg)
        return super()._refresh(
            obj_key="window_id",
            obj_id=self.window_id,
            list_cmd="list-windows",
            list_extra_args=("-a",),
        )

    @classmethod
    def from_window_id(cls, server: Server, window_id: str) -> Window:
        """Create Window from existing window_id."""
        window = fetch_obj(
            obj_key="window_id",
            obj_id=window_id,
            server=server,
            list_cmd="list-windows",
            list_extra_args=("-a",),
        )
        return cls(server=server, **window)

    @property
    def session(self) -> Session:
        """Parent session of window."""
        assert isinstance(self.session_id, str)
        from libtmux.session import Session

        return Session.from_session_id(server=self.server, session_id=self.session_id)

    @property
    def panes(self) -> QueryList[Pane]:
        """Panes contained by window.

        Can be accessed via
        :meth:`.panes.get() <libtmux._internal.query_list.QueryList.get()>` and
        :meth:`.panes.filter() <libtmux._internal.query_list.QueryList.filter()>`
        """
        panes: list[Pane] = [
            Pane(server=self.server, **obj)
            for obj in fetch_objs(
                list_cmd="list-panes",
                list_extra_args=["-t", str(self.window_id)],
                server=self.server,
            )
            if obj.get("window_id") == self.window_id
        ]

        return QueryList(panes)

    def search_panes(
        self,
        *,
        filter: str | None = None,  # noqa: A002
    ) -> QueryList[Pane]:
        """Panes in this window, optionally filtered by tmux.

        Like :attr:`Window.panes` but with a ``filter`` kwarg passed to
        ``$ tmux list-panes -t <window> -f <filter>``.

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
        :attr:`Window.panes` : unfiltered :class:`QueryList` of every
            pane in this window (Python-side ``.filter()`` runs against
            this).
        :ref:`native-filtering` : when to pick ``search_*`` over
            ``QueryList.filter()``.

        Examples
        --------
        >>> target_pane = window.split()
        >>> matches = window.search_panes(
        ...     filter=f'#{{m:{target_pane.pane_id},#{{pane_id}}}}'
        ... )
        >>> [p.pane_id for p in matches] == [target_pane.pane_id]
        True
        """
        panes: list[Pane] = [
            Pane(server=self.server, **obj)
            for obj in fetch_objs(
                list_cmd="list-panes",
                list_extra_args=["-t", str(self.window_id)],
                server=self.server,
                filter=filter,
            )
            if obj.get("window_id") == self.window_id
        ]

        return QueryList(panes)

    """
    Commands (pane-scoped)
    """

    def cmd(
        self,
        cmd: str,
        *args: t.Any,
        target: str | int | None = None,
    ) -> tmux_cmd:
        """Execute tmux subcommand within window context.

        Automatically binds target by adding  ``-t`` for object's window ID to the
        command. Pass ``target`` to keyword arguments to override.

        Examples
        --------
        Create a pane from a window:

        >>> window.cmd('split-window', '-P', '-F#{pane_id}').stdout[0]
        '%...'

        Magic, directly to a `Pane`:

        >>> Pane.from_pane_id(pane_id=session.cmd(
        ... 'split-window', '-P', '-F#{pane_id}').stdout[0], server=session.server)
        Pane(%... Window(@... ...:..., Session($1 libtmux_...)))

        Parameters
        ----------
        target : str, optional
            Optional custom target override. By default, the target is the window ID.

        Returns
        -------
        :meth:`server.cmd`
        """
        if target is None:
            target = self.window_id

        return self.server.cmd(cmd, *args, target=target)

    """
    Commands (tmux-like)
    """

    def select_pane(self, target_pane: str | int) -> Pane | None:
        """Select pane and return selected :class:`Pane`.

        ``$ tmux select-pane``.

        Parameters
        ----------
        target_pane : str
            'target_pane', '-U' ,'-D', '-L', '-R', or '-l'.

        Returns
        -------
        :class:`Pane`
        """
        if target_pane in {"-l", "-U", "-D", "-L", "-R"}:
            proc = self.cmd("select-pane", target_pane)
        else:
            proc = self.cmd("select-pane", target=target_pane)

        raise_if_stderr(proc, "select-pane")

        return self.active_pane

    def split(
        self,
        /,
        target: int | str | None = None,
        start_directory: StrPath | None = None,
        attach: bool = False,
        direction: PaneDirection | None = None,
        full_window_split: bool | None = None,
        zoom: bool | None = None,
        shell: str | None = None,
        size: str | int | None = None,
        percentage: int | None = None,
        environment: dict[str, str] | None = None,
        empty: bool | None = None,
    ) -> Pane:
        """Split window on active pane and return the created :class:`Pane`.

        Parameters
        ----------
        attach : bool, optional
            Make new window the current window after creating it, default
            True.
        start_directory : str or PathLike, optional
            Specifies the working directory in which the new window is created.
        direction : PaneDirection, optional
            Split in direction. If none is specified, assume down.
        full_window_split : bool, optional
            Split across full window width or height, rather than active pane.
        zoom : bool, optional
            Expand pane.
        shell : str, optional
            Execute a command on splitting the window. The pane will close
            when the command exits.

            NOTE: When this command exits the pane will close. This feature
            is useful for long-running processes where the closing of the
            window upon completion is desired.
        size : int, optional
            Cell/row count to occupy with respect to current window.
        percentage : int, optional
            Percentage (0-100) of the window to occupy (``-p`` flag).
            Mutually exclusive with *size*.

            .. versionadded:: 0.56
        environment : dict, optional
            Environmental variables for new pane. Passthrough to ``-e``.
        empty : bool, optional
            Create an empty pane with no command (``-E`` flag) instead of
            spawning the default shell. Requires tmux 3.7+. If used with
            tmux < 3.7, a warning is issued and the flag is ignored.

        Returns
        -------
        :class:`Pane`
            The newly created pane.
        """
        active_pane = self.active_pane or self.panes[0]
        return active_pane.split(
            target=target,
            start_directory=start_directory,
            attach=attach,
            direction=direction,
            full_window_split=full_window_split,
            zoom=zoom,
            shell=shell,
            size=size,
            percentage=percentage,
            environment=environment,
            empty=empty,
        )

    def new_pane(
        self,
        /,
        target: int | str | None = None,
        start_directory: StrPath | None = None,
        attach: bool = False,
        shell: str | None = None,
        environment: dict[str, str] | None = None,
        width: int | None = None,
        height: int | None = None,
        x: int | None = None,
        y: int | None = None,
        zoom: bool | None = None,
        empty: bool | None = None,
        style: str | None = None,
        active_border_style: str | None = None,
        inactive_border_style: str | None = None,
        message: str | None = None,
    ) -> Pane:
        """Create a floating :class:`Pane` in this window (``$ tmux new-pane``).

        Floating panes require tmux 3.7+. Delegates to :meth:`Pane.new_pane`
        on the active pane.

        Parameters
        ----------
        target : int or str, optional
            Custom *target-pane*.
        start_directory : str or PathLike, optional
            Working directory for the new pane (``-c``).
        attach : bool, optional
            Make the new pane active, default False (``-d`` otherwise).
        shell : str, optional
            Command to run; the pane closes when it exits.
        environment : dict, optional
            Environment variables for the new pane (``-e``).
        width : int, optional
            Width in cells (``-x``).
        height : int, optional
            Height in cells (``-y``).
        x : int, optional
            X position in cells (``-X``).
        y : int, optional
            Y position in cells (``-Y``).
        zoom : bool, optional
            Zoom the pane (``-Z``).
        empty : bool, optional
            Create an empty pane with no command (``-E``).
        style : str, optional
            Style for the floating pane (``-s``).
        active_border_style : str, optional
            Border style when the pane is active (``-S``).
        inactive_border_style : str, optional
            Border style when the pane is inactive (``-R``).
        message : str, optional
            Message line shown for the floating pane (``-m``).

        Returns
        -------
        :class:`Pane`
            The newly created floating pane.

        Examples
        --------
        >>> from libtmux.common import has_gte_version
        >>> if has_gte_version("3.7"):
        ...     floating = window.new_pane(width=40, height=10, shell="sleep 5")
        ...     is_floating = floating.pane_floating_flag
        ... else:
        ...     is_floating = "1"
        >>> is_floating
        '1'
        """
        active_pane = self.active_pane or self.panes[0]
        return active_pane.new_pane(
            target=target,
            start_directory=start_directory,
            attach=attach,
            shell=shell,
            environment=environment,
            width=width,
            height=height,
            x=x,
            y=y,
            zoom=zoom,
            empty=empty,
            style=style,
            active_border_style=active_border_style,
            inactive_border_style=inactive_border_style,
            message=message,
        )

    def resize(
        self,
        /,
        # Adjustments
        adjustment_direction: ResizeAdjustmentDirection | None = None,
        adjustment: int | None = None,
        # Manual
        height: int | None = None,
        width: int | None = None,
        # Expand / Shrink
        expand: bool | None = None,
        shrink: bool | None = None,
    ) -> Window:
        """Resize tmux window.

        Parameters
        ----------
        adjustment_direction : ResizeAdjustmentDirection, optional
            direction to adjust, ``Up``, ``Down``, ``Left``, ``Right``.
        adjustment : ResizeAdjustmentDirection, optional

        height : int, optional
            ``resize-window -y`` dimensions
        width : int, optional
            ``resize-window -x`` dimensions

        expand : bool
            expand window
        shrink : bool
            shrink window

        Raises
        ------
        :exc:`exc.LibTmuxException`,
        :exc:`exc.PaneAdjustmentDirectionRequiresAdjustment`

        Returns
        -------
        :class:`Window`

        Notes
        -----
        Three types of resizing are available:

        1. Adjustments: ``adjustment_direction`` and ``adjustment``.
        2. Manual resizing: ``height`` and / or ``width``.
        3. Expand or shrink: ``expand`` or ``shrink``.
        """
        tmux_args: tuple[str, ...] = ()

        # Adjustments
        if adjustment_direction:
            if adjustment is None:
                raise exc.WindowAdjustmentDirectionRequiresAdjustment
            tmux_args += (
                f"{RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP[adjustment_direction]}",
                str(adjustment),
            )
        elif height or width:
            # Manual resizing
            if height:
                tmux_args += (f"-y{int(height)}",)
            if width:
                tmux_args += (f"-x{int(width)}",)
        elif expand or shrink:
            if expand:
                tmux_args += ("-A",)
            elif shrink:
                tmux_args += ("-a",)

        proc = self.cmd("resize-window", *tmux_args)

        raise_if_stderr(proc, "resize-window")

        self.refresh()
        return self

    def last_pane(
        self,
        *,
        disable_input: bool | None = None,
        enable_input: bool | None = None,
        keep_zoom: bool | None = None,
    ) -> Pane | None:
        """Select the last (previously active) pane via ``$ tmux last-pane``.

        Parameters
        ----------
        disable_input : bool, optional
            Disable input to the pane (``-d`` flag).

            .. versionadded:: 0.56
        enable_input : bool, optional
            Enable input to the pane (``-e`` flag).

            .. versionadded:: 0.56
        keep_zoom : bool, optional
            Keep the window zoomed if zoomed (``-Z`` flag).

            .. versionadded:: 0.56

        Returns
        -------
        :class:`Pane` or None
            The selected pane, or None if no last pane exists.

        Examples
        --------
        >>> pane1 = window.active_pane
        >>> pane2 = window.split()
        >>> pane2.select()
        Pane(...)
        >>> result = window.last_pane()
        """
        tmux_args: tuple[str, ...] = ()

        if disable_input:
            tmux_args += ("-d",)

        if enable_input:
            tmux_args += ("-e",)

        if keep_zoom:
            tmux_args += ("-Z",)

        proc = self.cmd("last-pane", *tmux_args)

        raise_if_stderr(proc, "last-pane")

        return self.active_pane

    def select_layout(
        self,
        layout: str | None = None,
        *,
        spread: bool | None = None,
        next_layout: bool | None = None,
        previous_layout: bool | None = None,
    ) -> Window:
        """Select layout for window.

        Wrapper for ``$ tmux select-layout <layout>``.

        Parameters
        ----------
        layout : str, optional
            String of the layout, 'even-horizontal', 'tiled', etc. Entering
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
                Custom dimensions (see :term:`tmux(1)` manpages).
        spread : bool, optional
            Spread panes out evenly (``-E`` flag).

            .. versionadded:: 0.56
        next_layout : bool, optional
            Move to the next layout (``-n`` flag).

            .. versionadded:: 0.56
        previous_layout : bool, optional
            Move to the previous layout (``-p`` flag).

            .. versionadded:: 0.56

        Returns
        -------
        :class:`Window`
            Self, for method chaining.

        Raises
        ------
        :exc:`libtmux.exc.LibTmuxException`
            If tmux returns an error.
        ValueError
            If both *layout* and a flag (*spread*, *next_layout*,
            *previous_layout*) are specified.
        """
        flags = (spread, next_layout, previous_layout)
        if layout and any(flags):
            msg = "Cannot specify both layout and spread/next_layout/previous_layout"
            raise ValueError(msg)

        cmd = ["select-layout"]

        if spread:
            cmd.append("-E")

        if next_layout:
            cmd.append("-n")

        if previous_layout:
            cmd.append("-p")

        if layout:  # tmux allows select-layout without args
            cmd.append(layout)

        proc = self.cmd(*cmd)

        raise_if_stderr(proc, "select-layout")

        return self

    def next_layout(self) -> Window:
        """Cycle to the next layout via ``$ tmux next-layout``.

        >>> pane1 = window.active_pane
        >>> pane2 = window.split()
        >>> window.next_layout()
        Window(...)
        """
        proc = self.cmd("next-layout")

        raise_if_stderr(proc, "next-layout")

        return self

    def previous_layout(self) -> Window:
        """Cycle to the previous layout via ``$ tmux previous-layout``.

        >>> pane1 = window.active_pane
        >>> pane2 = window.split()
        >>> window.previous_layout()
        Window(...)
        """
        proc = self.cmd("previous-layout")

        raise_if_stderr(proc, "previous-layout")

        return self

    def link(
        self,
        target_session: str | Session,
        *,
        target_index: str | None = None,
        kill_existing: bool | None = None,
        after: bool | None = None,
        before: bool | None = None,
        detach: bool | None = None,
    ) -> None:
        """Link this window to another session via ``$ tmux link-window``.

        Parameters
        ----------
        target_session : str or Session
            Target session to link the window to.
        target_index : str, optional
            Target window index in the destination session.
        kill_existing : bool, optional
            Kill target window if it exists (``-k`` flag).
        after : bool, optional
            Insert after the target window (``-a`` flag).
        before : bool, optional
            Insert before the target window (``-b`` flag).
        detach : bool, optional
            Do not make the linked window active (``-d`` flag).

        Examples
        --------
        >>> w = session.new_window(window_name='link_test')
        >>> s2 = server.new_session(session_name='link_target')
        >>> w.link(s2)
        """
        tmux_args: tuple[str, ...] = ()

        if kill_existing:
            tmux_args += ("-k",)

        if after:
            tmux_args += ("-a",)

        if before:
            tmux_args += ("-b",)

        if detach:
            tmux_args += ("-d",)

        # Source: this window
        tmux_args += ("-s", f"{self.session_id}:{self.window_index}")

        # Target: destination session[:index]
        from libtmux.session import Session

        session_id = (
            target_session.session_id
            if isinstance(target_session, Session)
            else target_session
        )
        target = f"{session_id}:{target_index}" if target_index else str(session_id)
        tmux_args += ("-t", target)

        proc = self.server.cmd("link-window", *tmux_args)

        raise_if_stderr(proc, "link-window")

    def unlink(self, *, kill_if_last: bool | None = None) -> None:
        """Unlink this window from the current session via ``$ tmux unlink-window``.

        Parameters
        ----------
        kill_if_last : bool, optional
            Kill the window if it is the last window in the session (``-k``).

        Examples
        --------
        >>> w = session.new_window(window_name='unlink_test')
        >>> s2 = server.new_session(session_name='unlink_s2')
        >>> w.link(s2)
        >>> linked = [x for x in s2.windows if x.window_name == 'unlink_test']
        >>> linked[0].unlink()
        """
        tmux_args: tuple[str, ...] = ()

        if kill_if_last:
            tmux_args += ("-k",)

        proc = self.cmd("unlink-window", *tmux_args)

        raise_if_stderr(proc, "unlink-window")

    def rotate(
        self,
        *,
        upward: bool | None = None,
        downward: bool | None = None,
        keep_zoom: bool | None = None,
    ) -> Window:
        """Rotate pane positions in the window via ``$ tmux rotate-window``.

        Parameters
        ----------
        upward : bool, optional
            Rotate upward (``-U`` flag).
        downward : bool, optional
            Rotate downward (``-D`` flag).
        keep_zoom : bool, optional
            Keep the window zoomed if zoomed (``-Z`` flag).

        Returns
        -------
        :class:`Window`
            Self, for method chaining.

        Examples
        --------
        >>> pane1 = window.active_pane
        >>> pane2 = window.split()
        >>> window.rotate()
        Window(...)
        """
        tmux_args: tuple[str, ...] = ()

        if upward:
            tmux_args += ("-U",)

        if downward:
            tmux_args += ("-D",)

        if keep_zoom:
            tmux_args += ("-Z",)

        proc = self.cmd("rotate-window", *tmux_args)

        raise_if_stderr(proc, "rotate-window")

        return self

    def respawn(
        self,
        *,
        shell: str | None = None,
        start_directory: StrPath | None = None,
        environment: dict[str, str] | None = None,
        kill: bool | None = None,
    ) -> None:
        """Respawn the window process via ``$ tmux respawn-window``.

        Parameters
        ----------
        shell : str, optional
            Shell command to run in the respawned window.
        start_directory : str or PathLike, optional
            Working directory for the respawned window (``-c`` flag).
        environment : dict, optional
            Environment variables (``-e`` flag).
        kill : bool, optional
            Kill the current process before respawning (``-k`` flag).
            Required if the window is still active.

        Examples
        --------
        >>> window = session.new_window(window_name='respawn_test')
        >>> window.respawn(kill=True, shell='sh')
        """
        tmux_args: tuple[str, ...] = ()

        if kill:
            tmux_args += ("-k",)

        if start_directory is not None:
            start_path = pathlib.Path(start_directory).expanduser()
            tmux_args += (f"-c{start_path}",)

        if environment:
            for k, v in environment.items():
                tmux_args += (f"-e{k}={v}",)

        if shell:
            tmux_args += (shell,)

        proc = self.cmd("respawn-window", *tmux_args)

        raise_if_stderr(proc, "respawn-window")

    def swap(
        self,
        target: str | Window,
        *,
        detach: bool | None = None,
    ) -> None:
        """Swap this window with another via ``$ tmux swap-window``.

        Parameters
        ----------
        target : str or Window
            Target window to swap with. Can be a window ID string or Window.
        detach : bool, optional
            Do not change the active window (``-d`` flag).

        Examples
        --------
        >>> w1 = session.new_window(window_name='swap_a')
        >>> w2 = session.new_window(window_name='swap_b')
        >>> w1_idx = w1.window_index
        >>> w2_idx = w2.window_index
        >>> w1.swap(w2)
        >>> w1.window_index == w2_idx
        True
        >>> w2.window_index == w1_idx
        True
        """
        tmux_args: tuple[str, ...] = ()

        if detach:
            tmux_args += ("-d",)

        target_id = target.window_id if isinstance(target, Window) else target
        tmux_args += ("-s", str(target_id))

        proc = self.cmd("swap-window", *tmux_args)

        raise_if_stderr(proc, "swap-window")

        self.refresh()
        if isinstance(target, Window):
            target.refresh()

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
        """Display message at window scope via ``$ tmux display-message``.

        Like :meth:`Pane.display_message` but auto-injects ``-t @<window-id>``
        instead of a pane id. Window-scoped format reads such as
        ``#{window_zoomed_flag}`` or ``#{window_active_clients}`` no longer
        require dropping to :meth:`Window.cmd`.

        Parameters
        ----------
        cmd : str
            Format string to display or evaluate (e.g.
            ``"#{window_zoomed_flag}"``).

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
        Read the window's id format:

        >>> result = window.display_message("#{window_id}", get_text=True)
        >>> result[0].startswith("@")
        True

        Check zoom state (a common gap-#670 use case):

        >>> result = window.display_message(
        ...     "#{window_zoomed_flag}", get_text=True
        ... )
        >>> result[0] in {"0", "1"}
        True

        Notes
        -----
        Stderr from tmux is reported via :func:`warnings.warn`, not raised.
        Callers that want to escalate to an exception can wrap the call in
        :func:`warnings.catch_warnings` with ``filterwarnings("error")``.

        .. versionchanged:: 0.57
           Reports stderr via :func:`warnings.warn` instead of raising.
        """
        tmux_args: tuple[str, ...] = ()

        if get_text:
            tmux_args += ("-p",)

        if all_formats:
            tmux_args += ("-a",)

        if verbose:
            tmux_args += ("-v",)

        if no_expand:
            if has_gte_version("3.4", tmux_bin=self.server.tmux_bin):
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

    def rename_window(self, new_name: str) -> Window:
        """Rename window.

        Parameters
        ----------
        new_name : str
            name of the window

        Examples
        --------
        >>> window = session.active_window

        >>> window.rename_window('My project')
        Window(@1 1:My project, Session($1 ...))

        >>> window.rename_window('New name')
        Window(@1 1:New name, Session($1 ...))
        """
        lex = shlex.shlex(new_name)
        lex.escape = " "
        lex.whitespace_split = False

        proc = self.cmd("rename-window", new_name)
        raise_if_stderr(proc, "rename-window")

        self.window_name = new_name
        self.refresh()

        extra: dict[str, str] = {
            "tmux_subcommand": "rename-window",
        }
        if self.window_name is not None:
            extra["tmux_window"] = str(self.window_name)
        if self.window_id is not None:
            extra["tmux_target"] = str(self.window_id)
        logger.info("window renamed", extra=extra)

        return self

    def kill(
        self,
        all_except: bool | None = None,
    ) -> None:
        """Kill :class:`Window`.

        ``$ tmux kill-window``.

        Examples
        --------
        Kill a window:

        >>> window_1 = session.new_window()

        >>> window_1 in session.windows
        True

        >>> window_1.kill()

        >>> window_1 not in session.windows
        True

        Kill all windows except the current one:

        >>> one_window_to_rule_them_all = session.new_window()

        >>> other_windows = session.new_window(
        ...     ), session.new_window()

        >>> all([w in session.windows for w in other_windows])
        True

        >>> one_window_to_rule_them_all.kill(all_except=True)

        >>> all([w not in session.windows for w in other_windows])
        True

        >>> one_window_to_rule_them_all in session.windows
        True
        """
        flags: tuple[str, ...] = ()

        if all_except:
            flags += ("-a",)

        proc = self.cmd(
            "kill-window",
            *flags,
        )

        raise_if_stderr(proc, "kill-window")

        msg = "other windows killed" if all_except else "window killed"
        extra: dict[str, str] = {
            "tmux_subcommand": "kill-window",
        }
        if self.window_name is not None:
            extra["tmux_window"] = str(self.window_name)
        if self.window_id is not None:
            extra["tmux_target"] = str(self.window_id)
        logger.info(msg, extra=extra)

    def move_window(
        self,
        destination: str = "",
        session: str | None = None,
        *,
        after: bool | None = None,
        before: bool | None = None,
        no_select: bool | None = None,
        kill_target: bool | None = None,
        renumber: bool | None = None,
    ) -> Window:
        """Move current :class:`Window` object ``$ tmux move-window``.

        Parameters
        ----------
        destination : str, optional
            The ``target window`` or index to move the window to, default:
            empty string.
        session : str, optional
            The ``target session`` or index to move the window to, default:
            current session.
        after : bool, optional
            Insert after the target window (``-a`` flag).

            .. versionadded:: 0.56
        before : bool, optional
            Insert before the target window (``-b`` flag).

            .. versionadded:: 0.56
        no_select : bool, optional
            Do not make the moved window the current window (``-d`` flag).

            .. versionadded:: 0.56
        kill_target : bool, optional
            Kill the target window if it exists (``-k`` flag).

            .. versionadded:: 0.56
        renumber : bool, optional
            Renumber all windows in sequential order (``-r`` flag). This is a
            standalone operation — when used, no move is performed and other
            parameters are ignored.

            .. versionadded:: 0.56

        Returns
        -------
        :class:`Window`
            Self, for method chaining.

        Raises
        ------
        :exc:`libtmux.exc.LibTmuxException`
            If tmux returns an error.
        """
        tmux_args: tuple[str, ...] = ()

        if after:
            tmux_args += ("-a",)

        if before:
            tmux_args += ("-b",)

        if no_select:
            tmux_args += ("-d",)

        if kill_target:
            tmux_args += ("-k",)

        if renumber:
            tmux_args += ("-r",)

        session = session or self.session_id
        proc = self.cmd(
            "move-window",
            *tmux_args,
            f"-s{self.session_id}:{self.window_index}",
            target=f"{session}:{destination}",
        )

        raise_if_stderr(proc, "move-window")

        self.refresh()

        return self

    def new_window(
        self,
        window_name: str | None = None,
        *,
        start_directory: None = None,
        attach: bool = False,
        window_index: str = "",
        window_shell: str | None = None,
        environment: dict[str, str] | None = None,
        direction: WindowDirection | None = None,
    ) -> Window:
        """Create new window respective of current window's position.

        See Also
        --------
        :meth:`Session.new_window()`

        Examples
        --------
        >>> window_initial = session.new_window(window_name='Example')
        >>> window_initial
        Window(@... 2:Example, Session($1 libtmux_...))
        >>> window_initial.window_index
        '2'

        >>> window_before = window_initial.new_window(
        ... window_name='Window before', direction=WindowDirection.Before)
        >>> window_initial.refresh()
        >>> window_before
        Window(@... 2:Window before, Session($1 libtmux_...))
        >>> window_initial
        Window(@... 3:Example, Session($1 libtmux_...))

        >>> window_after = window_initial.new_window(
        ... window_name='Window after', direction=WindowDirection.After)
        >>> window_initial.refresh()
        >>> window_after.refresh()
        >>> window_after
        Window(@... 4:Window after, Session($1 libtmux_...))
        >>> window_initial
        Window(@... 3:Example, Session($1 libtmux_...))
        >>> window_before
        Window(@... 2:Window before, Session($1 libtmux_...))
        """
        return self.session.new_window(
            window_name=window_name,
            start_directory=start_directory,
            attach=attach,
            window_index=window_index,
            window_shell=window_shell,
            environment=environment,
            direction=direction,
            target_window=self.window_id,
        )

    #
    # Climbers
    #
    def select(self) -> Window:
        """Select window.

        To select a window object asynchrously. If a ``window`` object exists
        and is no longer the current window, ``w.select_window()``
        will make ``w`` the current window.

        Examples
        --------
        >>> window = session.active_window
        >>> new_window = session.new_window()
        >>> session.refresh()
        >>> active_windows = [w for w in session.windows if w.window_active == '1']

        >>> new_window.window_active == '1'
        False

        >>> new_window.select()
        Window(...)

        >>> new_window.window_active == '1'
        True
        """
        proc = self.cmd("select-window")

        raise_if_stderr(proc, "select-window")

        self.refresh()

        return self

    #
    # Computed properties
    #
    @property
    def active_pane(self) -> Pane | None:
        """Return attached :class:`Pane`."""
        panes = self.panes.filter(pane_active="1")
        if len(panes) > 0:
            return panes[0]
        return None

    #
    # Dunder
    #
    def __eq__(self, other: object) -> bool:
        """Equal operator for :class:`Window` object."""
        if isinstance(other, Window):
            return self.window_id == other.window_id
        return False

    def __repr__(self) -> str:
        """Representation of :class:`Window` object."""
        return (
            f"{self.__class__.__name__}({self.window_id} "
            f"{self.window_index}:{self.window_name}, {self.session})"
        )

    #
    # Aliases
    #
    @property
    def id(self) -> str | None:
        """Alias of :attr:`Window.window_id`.

        >>> window.id
        '@1'

        >>> window.id == window.window_id
        True
        """
        return self.window_id

    @property
    def name(self) -> str | None:
        """Alias of :attr:`Window.window_name`.

        >>> window.name
        '...'

        >>> window.name == window.window_name
        True
        """
        return self.window_name

    @property
    def index(self) -> str | None:
        """Alias of :attr:`Window.window_index`.

        >>> window.index
        '1'

        >>> window.index == window.window_index
        True
        """
        return self.window_index

    @property
    def height(self) -> str | None:
        """Alias of :attr:`Window.window_height`.

        >>> window.height.isdigit()
        True

        >>> window.height == window.window_height
        True
        """
        return self.window_height

    @property
    def width(self) -> str | None:
        """Alias of :attr:`Window.window_width`.

        >>> window.width.isdigit()
        True

        >>> window.width == window.window_width
        True
        """
        return self.window_width

    #
    # Legacy: Redundant stuff we want to remove
    #
    def split_window(
        self,
        target: int | str | None = None,
        start_directory: StrPath | None = None,
        attach: bool = False,
        vertical: bool = True,
        shell: str | None = None,
        size: str | int | None = None,
        percent: int | None = None,  # deprecated
        environment: dict[str, str] | None = None,
    ) -> Pane:
        """Split window and return the created :class:`Pane`.

        Notes
        -----
        .. deprecated:: 0.33.0

           Deprecated in favor of :meth:`.split()`.

        .. versionchanged:: 0.28.0

           ``attach`` default changed from ``True`` to ``False``.

        .. deprecated:: 0.28.0

           ``percent=25`` deprecated in favor of ``size="25%"``.
        """
        raise exc.DeprecatedError(
            deprecated="Window.split_window()",
            replacement="Window.split()",
            version="0.33.0",
        )

    @property
    def attached_pane(self) -> Pane | None:
        """Return attached :class:`Pane`.

        Notes
        -----
        .. deprecated:: 0.31

           Deprecated in favor of :meth:`.active_pane`.
        """
        raise exc.DeprecatedError(
            deprecated="Window.attached_pane",
            replacement="Window.active_pane",
            version="0.31.0",
        )

    def select_window(self) -> Window:
        """Select window.

        Notes
        -----
        .. deprecated:: 0.30

           Deprecated in favor of :meth:`.select()`.
        """
        raise exc.DeprecatedError(
            deprecated="Window.select_window()",
            replacement="Window.select()",
            version="0.30.0",
        )

    def kill_window(self) -> None:
        """Kill the current :class:`Window` object. ``$ tmux kill-window``.

        Notes
        -----
        .. deprecated:: 0.30

           Deprecated in favor of :meth:`.kill()`.
        """
        raise exc.DeprecatedError(
            deprecated="Window.kill_window()",
            replacement="Window.kill()",
            version="0.30.0",
        )

    def set_window_option(
        self,
        option: str,
        value: int | str,
    ) -> Window:
        """Set option for tmux window. Deprecated by :meth:`Window.set_option()`.

        .. deprecated:: 0.50

           Deprecated by :meth:`Window.set_option()`.

        """
        warnings.warn(
            "Window.set_window_option() is deprecated in favor of Window.set_option()",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.set_option(option=option, value=value)

    def show_window_options(self, g: bool | None = False) -> WindowOptionDict:
        """Show options for tmux window. Deprecated by :meth:`Window.show_options()`.

        .. deprecated:: 0.50

           Deprecated by :meth:`Window.show_options()`.

        """
        warnings.warn(
            "Window.show_window_options() is deprecated"
            " in favor of Window.show_options()",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.show_options(
            global_=g or False,
            scope=OptionScope.Window,
        )

    def show_window_option(
        self,
        option: str,
        g: bool = False,
    ) -> str | int | None:
        """Return option for target window. Deprecated by :meth:`Window.show_option()`.

        .. deprecated:: 0.50

           Deprecated by :meth:`Window.show_option()`.

        """
        warnings.warn(
            "Window.show_window_option() is deprecated"
            " in favor of Window.show_option()",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.show_option(
            option=option,
            global_=g,
        )

    def get(self, key: str, default: t.Any | None = None) -> t.Any:
        """Return key-based lookup. Deprecated by attributes.

        .. deprecated:: 0.17

           Deprecated by attribute lookup.e.g. ``window['window_name']`` is now
           accessed via ``window.window_name``.

        """
        raise exc.DeprecatedError(
            deprecated="Window.get()",
            replacement="direct attribute access (e.g., window.window_name)",
            version="0.17.0",
        )

    def __getitem__(self, key: str) -> t.Any:
        """Return item lookup by key. Deprecated in favor of attributes.

        .. deprecated:: 0.17

           Deprecated in favor of attributes. e.g. ``window['window_name']`` is now
           accessed via ``window.window_name``.

        """
        raise exc.DeprecatedError(
            deprecated="Window[key] lookup",
            replacement="direct attribute access (e.g., window.window_name)",
            version="0.17.0",
        )

    def get_by_id(self, pane_id: str) -> Pane | None:
        """Return pane by id. Deprecated in favor of :meth:`.panes.get()`.

        .. deprecated:: 0.16

           Deprecated by :meth:`.panes.get()`.

        """
        raise exc.DeprecatedError(
            deprecated="Window.get_by_id()",
            replacement="Window.panes.get(pane_id=..., default=None)",
            version="0.16.0",
        )

    def where(self, kwargs: dict[str, t.Any]) -> list[Pane]:
        """Filter through panes, return list of :class:`Pane`.

        .. deprecated:: 0.17

           Deprecated by :meth:`.panes.filter()`.

        """
        raise exc.DeprecatedError(
            deprecated="Window.where()",
            replacement="Window.panes.filter()",
            version="0.17.0",
        )

    def find_where(self, kwargs: dict[str, t.Any]) -> Pane | None:
        """Filter through panes, return first :class:`Pane`.

        .. deprecated:: 0.17

           Slated to be removed in favor of :meth:`.panes.get()`.

        """
        raise exc.DeprecatedError(
            deprecated="Window.find_where()",
            replacement="Window.panes.get(default=None, **kwargs)",
            version="0.17.0",
        )

    def _list_panes(self) -> list[PaneDict]:
        """Return list of panes (deprecated in favor of :meth:`.panes`).

        .. deprecated:: 0.17

           Slated to be removed in favor of :attr:`.panes`.

        """
        raise exc.DeprecatedError(
            deprecated="Window._list_panes()",
            replacement="Window.panes property",
            version="0.17.0",
        )

    @property
    def _panes(self) -> list[PaneDict]:
        """Property / alias to return :meth:`~._list_panes`.

        .. deprecated:: 0.17

           Slated to be removed in favor of :attr:`.panes`.

        """
        raise exc.DeprecatedError(
            deprecated="Window._panes",
            replacement="Window.panes property",
            version="0.17.0",
        )

    def list_panes(self) -> list[Pane]:
        """Return list of :class:`Pane` for the window.

        .. deprecated:: 0.17

           Slated to be removed in favor of :attr:`.panes`.

        """
        raise exc.DeprecatedError(
            deprecated="Window.list_panes()",
            replacement="Window.panes property",
            version="0.17.0",
        )

    @property
    def children(self) -> QueryList[Pane]:
        """Was used by TmuxRelationalObject (but that's longer used in this class).

        .. deprecated:: 0.17

           Slated to be removed in favor of :attr:`.panes`.

        """
        raise exc.DeprecatedError(
            deprecated="Window.children",
            replacement="Window.panes property",
            version="0.17.0",
        )
