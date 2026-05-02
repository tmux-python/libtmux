"""Pythonization of the :ref:`tmux(1)` pane.

libtmux.pane
~~~~~~~~~~~~

"""

from __future__ import annotations

import dataclasses
import logging
import pathlib
import typing as t

from libtmux import exc
from libtmux.common import tmux_cmd
from libtmux.constants import (
    PANE_DIRECTION_FLAG_MAP,
    RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP,
    OptionScope,
    PaneDirection,
    ResizeAdjustmentDirection,
)
from libtmux.formats import FORMAT_SEPARATOR
from libtmux.hooks import HooksMixin
from libtmux.neo import Obj, fetch_obj
from libtmux.options import OptionsMixin

if t.TYPE_CHECKING:
    import sys
    import types

    from libtmux._internal.types import StrPath

    from .server import Server
    from .session import Session
    from .window import Window

    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing_extensions import Self

logger = logging.getLogger(__name__)


@dataclasses.dataclass()
class Pane(
    Obj,
    OptionsMixin,
    HooksMixin,
):
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

    The pane can be used as a context manager to ensure proper cleanup:

    >>> with window.split() as pane:
    ...     pane.send_keys('echo "Hello"')
    ...     # Do work with the pane
    ...     # Pane will be killed automatically when exiting the context

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

    default_option_scope: OptionScope | None = OptionScope.Pane
    default_hook_scope: OptionScope | None = OptionScope.Pane
    server: Server

    def __enter__(self) -> Self:
        """Enter the context, returning self.

        Returns
        -------
        :class:`Pane`
            The pane instance
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Exit the context, killing the pane if it exists.

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
            self.pane_id is not None
            and len(self.window.panes.filter(pane_id=self.pane_id)) > 0
        ):
            self.kill()

    def refresh(self) -> None:
        """Refresh pane attributes from tmux."""
        assert isinstance(self.pane_id, str)
        return super()._refresh(
            obj_key="pane_id",
            obj_id=self.pane_id,
            list_extra_args=("-a",),
        )

    @classmethod
    def from_pane_id(cls, server: Server, pane_id: str) -> Pane:
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
    def window(self) -> Window:
        """Parent window of pane."""
        assert isinstance(self.window_id, str)
        from libtmux.window import Window

        return Window.from_window_id(server=self.server, window_id=self.window_id)

    @property
    def session(self) -> Session:
        """Parent session of pane."""
        return self.window.session

    """
    Commands (pane-scoped)
    """

    def cmd(
        self,
        cmd: str,
        *args: t.Any,
        target: str | int | None = None,
    ) -> tmux_cmd:
        """Execute tmux subcommand within pane context.

        Automatically binds target by adding  ``-t`` for object's pane ID to the
        command. Pass ``target`` to keyword arguments to override.

        Examples
        --------
        >>> pane.cmd('split-window', '-P').stdout[0]
        'libtmux...:...'

        From raw output to an enriched `Pane` object:

        >>> Pane.from_pane_id(pane_id=pane.cmd(
        ... 'split-window', '-P', '-F#{pane_id}').stdout[0], server=pane.server)
        Pane(%... Window(@... ...:..., Session($1 libtmux_...)))

        Parameters
        ----------
        target : str, optional
            Optional custom target override. By default, the target is the pane ID.

        Returns
        -------
        :meth:`server.cmd`
        """
        if target is None:
            target = self.pane_id

        return self.server.cmd(cmd, *args, target=target)

    """
    Commands (tmux-like)
    """

    def resize(
        self,
        /,
        # Adjustments
        adjustment_direction: ResizeAdjustmentDirection | None = None,
        adjustment: int | None = None,
        # Manual
        height: str | int | None = None,
        width: str | int | None = None,
        # Zoom
        zoom: bool | None = None,
        # Mouse
        mouse: bool | None = None,
        # Optional flags
        trim_below: bool | None = None,
    ) -> Pane:
        """Resize tmux pane.

        Parameters
        ----------
        adjustment_direction : ResizeAdjustmentDirection, optional
            direction to adjust, ``Up``, ``Down``, ``Left``, ``Right``.
        adjustment : ResizeAdjustmentDirection, optional

        height : int, optional
            ``resize-pane -y`` dimensions
        width : int, optional
            ``resize-pane -x`` dimensions

        zoom : bool
            expand pane

        mouse : bool
            resize via mouse

        trim_below : bool
            trim below cursor

        Raises
        ------
        :exc:`exc.LibTmuxException`,
        :exc:`exc.PaneAdjustmentDirectionRequiresAdjustment`,
        :exc:`exc.RequiresDigitOrPercentage`

        Returns
        -------
        :class:`Pane`

        Notes
        -----
        Three types of resizing are available:

        1. Adjustments: ``adjustment_direction`` and ``adjustment``.
        2. Manual resizing: ``height`` and / or ``width``.
        3. Zoom / Unzoom: ``zoom``.
        """
        tmux_args: tuple[str, ...] = ()

        # Adjustments
        if adjustment_direction:
            if adjustment is None:
                raise exc.PaneAdjustmentDirectionRequiresAdjustment
            tmux_args += (
                f"{RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP[adjustment_direction]}",
                str(adjustment),
            )
        elif height or width:
            # Manual resizing
            if height:
                if (
                    isinstance(height, str)
                    and not height.isdigit()
                    and not height.endswith("%")
                ):
                    raise exc.RequiresDigitOrPercentage
                tmux_args += (f"-y{height}",)

            if width:
                if (
                    isinstance(width, str)
                    and not width.isdigit()
                    and not width.endswith("%")
                ):
                    raise exc.RequiresDigitOrPercentage
                tmux_args += (f"-x{width}",)
        elif zoom:
            # Zoom / Unzoom
            tmux_args += ("-Z",)
        elif mouse:
            tmux_args += ("-M",)

        if trim_below:
            tmux_args += ("-T",)

        proc = self.cmd("resize-pane", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        self.refresh()
        return self

    def capture_pane(
        self,
        start: t.Literal["-"] | int | None = None,
        end: t.Literal["-"] | int | None = None,
        *,
        escape_sequences: bool = False,
        escape_non_printable: bool = False,
        join_wrapped: bool = False,
        preserve_trailing: bool = False,
        trim_trailing: bool = False,
        alternate_screen: bool = False,
        quiet: bool = False,
        mode_screen: bool = False,
    ) -> list[str]:
        r"""Capture text from pane.

        ``$ tmux capture-pane`` to pane.
        ``$ tmux capture-pane -S -10`` to pane.
        ``$ tmux capture-pane -E 3`` to pane.
        ``$ tmux capture-pane -S - -E -`` to pane.

        Parameters
        ----------
        start : str | int, optional
            Specify the starting line number.
            Zero is the first line of the visible pane.
            Positive numbers are lines in the visible pane.
            Negative numbers are lines in the history.
            ``-`` is the start of the history.
            Default: None
        end : str | int, optional
            Specify the ending line number.
            Zero is the first line of the visible pane.
            Positive numbers are lines in the visible pane.
            Negative numbers are lines in the history.
            ``-`` is the end of the visible pane.
            Default: None
        escape_sequences : bool, optional
            Include ANSI escape sequences for text and background attributes
            (``-e`` flag). Useful for capturing colored output.
            Default: False
        escape_non_printable : bool, optional
            Escape non-printable characters as octal ``\\xxx`` format
            (``-C`` flag). Useful for binary-safe capture.
            Default: False
        join_wrapped : bool, optional
            Join wrapped lines and preserve trailing spaces (``-J`` flag).
            Lines that were wrapped by tmux will be joined back together.
            Default: False
        preserve_trailing : bool, optional
            Preserve trailing spaces at each line's end (``-N`` flag).
            Default: False
        trim_trailing : bool, optional
            Trim trailing positions with no characters (``-T`` flag).
            Only includes characters up to the last used cell.
            Requires tmux 3.4+. If used with tmux < 3.4, a warning
            is issued and the flag is ignored.
            Default: False
        alternate_screen : bool, optional
            Capture from the alternate screen (``-a`` flag).
            Default: False

            .. versionadded:: 0.45
        quiet : bool, optional
            Suppress errors silently (``-q`` flag).
            Default: False

            .. versionadded:: 0.45
        mode_screen : bool, optional
            Capture from the mode screen (e.g. copy mode) instead of the
            pane (``-M`` flag). Requires tmux 3.6+.
            Default: False

            .. versionadded:: 0.45

        Returns
        -------
        list[str]
            Captured pane content.

        Examples
        --------
        >>> pane = window.split(shell='sh')
        >>> pane.capture_pane()
        ['$']

        >>> pane.send_keys('echo "Hello world"', enter=True)

        >>> pane.capture_pane()
        ['$ echo "Hello world"', 'Hello world', '$']

        >>> print(chr(10).join(pane.capture_pane()))
        $ echo "Hello world"
        Hello world
        $
        """
        import warnings

        from libtmux.common import has_gte_version

        cmd = ["capture-pane", "-p"]
        if start is not None:
            cmd.extend(["-S", str(start)])
        if end is not None:
            cmd.extend(["-E", str(end)])
        if escape_sequences:
            cmd.append("-e")
        if escape_non_printable:
            cmd.append("-C")
        if join_wrapped:
            cmd.append("-J")
        if preserve_trailing:
            cmd.append("-N")
        if trim_trailing:
            if has_gte_version("3.4", tmux_bin=self.server.tmux_bin):
                cmd.append("-T")
            else:
                warnings.warn(
                    "trim_trailing requires tmux 3.4+, ignoring",
                    stacklevel=2,
                )
        if alternate_screen:
            cmd.append("-a")
        if quiet:
            cmd.append("-q")
        if mode_screen:
            if has_gte_version("3.6", tmux_bin=self.server.tmux_bin):
                cmd.append("-M")
            else:
                warnings.warn(
                    "mode_screen requires tmux 3.6+, ignoring",
                    stacklevel=2,
                )
        return self.cmd(*cmd).stdout

    def send_keys(
        self,
        cmd: str,
        enter: bool | None = True,
        suppress_history: bool | None = False,
        literal: bool | None = False,
        reset: bool | None = None,
        copy_mode_cmd: str | None = None,
        repeat: int | None = None,
        expand_formats: bool | None = None,
        hex_keys: bool | None = None,
        target_client: str | None = None,
        key_name: bool | None = None,
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
            Send keys literally, default False.
        reset : bool, optional
            Reset terminal state before sending keys (``-R`` flag).

            .. versionadded:: 0.45
        copy_mode_cmd : str, optional
            Send a command to copy mode instead of keys (``-X`` flag).
            When set, *cmd* is ignored.

            .. versionadded:: 0.45
        repeat : int, optional
            Repeat count for the key (``-N`` flag).

            .. versionadded:: 0.45
        expand_formats : bool, optional
            Expand tmux format strings in keys (``-F`` flag).

            .. versionadded:: 0.45
        hex_keys : bool, optional
            Send keys as hex values (``-H`` flag).

            .. versionadded:: 0.45
        target_client : str, optional
            Specify a target client (``-c`` flag). Requires tmux 3.4+.

            .. versionadded:: 0.45
        key_name : bool, optional
            Handle keys as key names (``-K`` flag). Requires tmux 3.4+.

            .. versionadded:: 0.45

        Examples
        --------
        >>> pane = window.split(shell='sh')
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
        import warnings

        from libtmux.common import has_gte_version

        prefix = " " if suppress_history else ""

        tmux_args: tuple[str, ...] = ()

        if reset:
            tmux_args += ("-R",)

        if expand_formats:
            tmux_args += ("-F",)

        if hex_keys:
            tmux_args += ("-H",)

        if key_name:
            if has_gte_version("3.4", tmux_bin=self.server.tmux_bin):
                tmux_args += ("-K",)
            else:
                warnings.warn(
                    "key_name requires tmux 3.4+, ignoring",
                    stacklevel=2,
                )

        if literal:
            tmux_args += ("-l",)

        if repeat is not None:
            tmux_args += ("-N", str(repeat))

        if target_client is not None:
            if has_gte_version("3.4", tmux_bin=self.server.tmux_bin):
                tmux_args += ("-c", target_client)
            else:
                warnings.warn(
                    "target_client requires tmux 3.4+, ignoring",
                    stacklevel=2,
                )

        if copy_mode_cmd is not None:
            tmux_args += ("-X",)
            self.cmd("send-keys", *tmux_args, copy_mode_cmd)
        else:
            self.cmd("send-keys", *tmux_args, prefix + cmd)

        if enter and copy_mode_cmd is None:
            self.enter()

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
        update_pane: bool | None = ...,
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
        update_pane: bool | None = ...,
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
        update_pane: bool | None = None,
    ) -> list[str] | None:
        """Display message to pane.

        Displays a message in target-client status line.
        The ``get_text=False`` path renders in the status line and is not
        programmatically verifiable; only ``get_text=True`` returns output.

        Parameters
        ----------
        cmd : str
            Special parameters to request from pane.
        get_text : bool, optional
            Returns only text without displaying a message in
            target-client status line.
        format_string : str, optional
            Format string for output (``-F`` flag).

            .. versionadded:: 0.45
        all_formats : bool, optional
            List all format variables (``-a`` flag).

            .. versionadded:: 0.45
        verbose : bool, optional
            Show format variable types (``-v`` flag).

            .. versionadded:: 0.45
        no_expand : bool, optional
            Suppress format expansion; output is returned as a literal string
            (``-l`` flag). Requires tmux 3.4+.

            .. versionadded:: 0.45
        target_client : str, optional
            Target client (``-c`` flag).

            .. versionadded:: 0.45
        delay : int, optional
            Display time in milliseconds (``-d`` flag).

            .. versionadded:: 0.45
        notify : bool, optional
            Do not wait for input (``-N`` flag).

            .. versionadded:: 0.45
        update_pane : bool, optional
            Allow the pane to keep updating while the message is displayed
            (``-C`` flag). By default tmux freezes the pane while a status
            message is shown. Requires tmux 3.6+ (introduced upstream by
            commit ``80eb460f``).

            .. versionadded:: 0.45

        Returns
        -------
        list[str] | None
            Message output if get_text is True, otherwise None.
        """
        import warnings

        from libtmux.common import has_gte_version

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

        if update_pane:
            if has_gte_version("3.6", tmux_bin=self.server.tmux_bin):
                tmux_args += ("-C",)
            else:
                warnings.warn(
                    "update_pane requires tmux 3.6+, ignoring",
                    stacklevel=2,
                )

        if target_client is not None:
            tmux_args += ("-c", target_client)

        if delay is not None:
            tmux_args += ("-d", str(delay))

        if format_string is not None:
            tmux_args += ("-F", format_string)

        if cmd:
            tmux_args += (cmd,)

        proc = self.cmd("display-message", *tmux_args)

        if get_text:
            return proc.stdout

        return None

    def kill(
        self,
        all_except: bool | None = None,
    ) -> None:
        """Kill :class:`Pane`.

        ``$ tmux kill-pane``.

        Examples
        --------
        Kill a pane:

        >>> pane_1 = pane.split()

        >>> pane_1 in window.panes
        True

        >>> pane_1.kill()

        >>> pane_1 not in window.panes
        True

        Kill all panes except the current one:

        >>> pane.window.resize(height=100, width=100)
        Window(@1 1...)

        >>> one_pane_to_rule_them_all = pane.split()

        >>> other_panes = pane.split(
        ...     ), pane.split()

        >>> all([p in window.panes for p in other_panes])
        True

        >>> one_pane_to_rule_them_all.kill(all_except=True)

        >>> all([p not in window.panes for p in other_panes])
        True

        >>> one_pane_to_rule_them_all in window.panes
        True
        """
        flags: tuple[str, ...] = ()

        if all_except:
            flags += ("-a",)

        proc = self.cmd(
            "kill-pane",
            *flags,
        )

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        extra: dict[str, str] = {
            "tmux_subcommand": "kill-pane",
        }
        if self.pane_id is not None:
            extra["tmux_pane"] = str(self.pane_id)
            extra["tmux_target"] = str(self.pane_id)
        msg = "other panes killed" if all_except else "pane killed"
        logger.info(msg, extra=extra)

    """
    Commands ("climber"-helpers)

    These are commands that climb to the parent scope's methods with
    additional scoped window info.
    """

    def select(
        self,
        *,
        direction: ResizeAdjustmentDirection | None = None,
        last: bool | None = None,
        keep_zoom: bool | None = None,
        mark: bool | None = None,
        clear_mark: bool | None = None,
        disable_input: bool | None = None,
        enable_input: bool | None = None,
    ) -> Pane:
        """Select pane.

        Parameters
        ----------
        direction : ResizeAdjustmentDirection, optional
            Select the pane in the given direction (``-U``, ``-D``, ``-L``,
            ``-R``).

            .. versionadded:: 0.45
        last : bool, optional
            Select the last (previously selected) pane (``-l`` flag).

            .. versionadded:: 0.45
        keep_zoom : bool, optional
            Keep the window zoomed if it was zoomed (``-Z`` flag).

            .. versionadded:: 0.45
        mark : bool, optional
            Set the marked pane (``-m`` flag).

            .. versionadded:: 0.45
        clear_mark : bool, optional
            Clear the marked pane (``-M`` flag).

            .. versionadded:: 0.45
        disable_input : bool, optional
            Disable input to the pane (``-d`` flag).

            .. versionadded:: 0.45
        enable_input : bool, optional
            Enable input to the pane (``-e`` flag).

            .. versionadded:: 0.45

        Returns
        -------
        :class:`Pane`
            Self, for method chaining.

        Examples
        --------
        >>> pane = window.active_pane
        >>> new_pane = window.split()
        >>> pane.refresh()
        >>> active_panes = [p for p in window.panes if p.pane_active == '1']

        >>> pane in active_panes
        True
        >>> new_pane in active_panes
        False

        >>> new_pane.pane_active == '1'
        False

        >>> new_pane.select()
        Pane(...)

        >>> new_pane.pane_active == '1'
        True
        """
        tmux_args: tuple[str, ...] = ()

        if direction is not None:
            tmux_args += (RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP[direction],)

        if last:
            tmux_args += ("-l",)

        if keep_zoom:
            tmux_args += ("-Z",)

        if mark:
            tmux_args += ("-m",)

        if clear_mark:
            tmux_args += ("-M",)

        if disable_input:
            tmux_args += ("-d",)

        if enable_input:
            tmux_args += ("-e",)

        proc = self.cmd("select-pane", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        self.refresh()

        return self

    def select_pane(self) -> Pane:
        """Select pane.

        Notes
        -----
        .. deprecated:: 0.30

           Deprecated in favor of :meth:`.select()`.
        """
        raise exc.DeprecatedError(
            deprecated="Pane.select_pane()",
            replacement="Pane.select()",
            version="0.30.0",
        )

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
    ) -> Pane:
        """Split window and return :class:`Pane`, by default beneath current pane.

        Parameters
        ----------
        target : optional
            Optional, custom *target-pane*, used by :meth:`Window.split`.
        attach : bool, optional
            make new window the current window after creating it, default
            True.
        start_directory : str or PathLike, optional
            specifies the working directory in which the new window is created.
        direction : PaneDirection, optional
            split in direction. If none is specified, assume down.
        full_window_split: bool, optional
            split across full window width or height, rather than active pane.
        zoom: bool, optional
            expand pane
        shell : str, optional
            execute a command on splitting the window.  The pane will close
            when the command exits.

            NOTE: When this command exits the pane will close.  This feature
            is useful for long-running processes where the closing of the
            window upon completion is desired.
        size: int, optional
            Cell/row count to occupy with respect to current window.
        percentage: int, optional
            Percentage (0-100) of the window to occupy (``-p`` flag).
            Mutually exclusive with *size*.

            .. versionadded:: 0.45
        environment: dict, optional
            Environmental variables for new pane. Passthrough to ``-e``.

        Examples
        --------
        >>> (pane.at_left, pane.at_right,
        ...  pane.at_top, pane.at_bottom)
        (True, True,
        True, True)

        >>> new_pane = pane.split()

        >>> (new_pane.at_left, new_pane.at_right,
        ...  new_pane.at_top, new_pane.at_bottom)
        (True, True,
        False, True)

        >>> right_pane = pane.split(direction=PaneDirection.Right)

        >>> (right_pane.at_left, right_pane.at_right,
        ...  right_pane.at_top, right_pane.at_bottom)
        (False, True,
        True, False)

        >>> left_pane = pane.split(direction=PaneDirection.Left)

        >>> (left_pane.at_left, left_pane.at_right,
        ...  left_pane.at_top, left_pane.at_bottom)
        (True, False,
        True, False)

        >>> top_pane = pane.split(direction=PaneDirection.Above)

        >>> (top_pane.at_left, top_pane.at_right,
        ...  top_pane.at_top, top_pane.at_bottom)
        (False, False,
        True, False)

        >>> pane = session.new_window().active_pane

        >>> top_pane = pane.split(direction=PaneDirection.Above, full_window_split=True)

        >>> (top_pane.at_left, top_pane.at_right,
        ...  top_pane.at_top, top_pane.at_bottom)
        (True, True,
        True, False)

        >>> bottom_pane = pane.split(
        ... direction=PaneDirection.Below,
        ... full_window_split=True)

        >>> (bottom_pane.at_left, bottom_pane.at_right,
        ...  bottom_pane.at_top, bottom_pane.at_bottom)
        (True, True,
        False, True)
        """
        tmux_formats = ["#{pane_id}" + FORMAT_SEPARATOR]

        tmux_args: tuple[str, ...] = ()

        if direction:
            tmux_args += tuple(PANE_DIRECTION_FLAG_MAP[direction])
        else:
            tmux_args += tuple(PANE_DIRECTION_FLAG_MAP[PaneDirection.Below])

        if size is not None and percentage is not None:
            msg = "Cannot specify both size and percentage"
            raise ValueError(msg)

        if size is not None:
            tmux_args += (f"-l{size}",)

        if percentage is not None:
            tmux_args += (f"-p{percentage}",)

        if full_window_split:
            tmux_args += ("-f",)

        if zoom:
            tmux_args += ("-Z",)

        tmux_args += ("-P", "-F{}".format("".join(tmux_formats)))  # output

        if start_directory:
            start_path = pathlib.Path(start_directory).expanduser()
            tmux_args += (f"-c{start_path}",)

        if not attach:
            tmux_args += ("-d",)

        if environment:
            for k, v in environment.items():
                tmux_args += (f"-e{k}={v}",)

        if shell:
            tmux_args += (shell,)

        pane_cmd = self.cmd("split-window", *tmux_args, target=target)

        if pane_cmd.stderr:
            if "pane too small" in pane_cmd.stderr:
                raise exc.LibTmuxException(pane_cmd.stderr)

            raise exc.LibTmuxException(
                pane_cmd.stderr,
                self.__dict__,
                self.window.panes,
            )

        pane_output = pane_cmd.stdout[0]

        pane_formatters = dict(
            zip(["pane_id"], pane_output.split(FORMAT_SEPARATOR), strict=False),
        )

        pane = self.from_pane_id(server=self.server, pane_id=pane_formatters["pane_id"])

        extra: dict[str, str] = {
            "tmux_subcommand": "split-window",
            "tmux_pane": str(pane.pane_id),
        }
        if self.session.session_name is not None:
            extra["tmux_session"] = str(self.session.session_name)
        if self.window.window_name is not None:
            extra["tmux_window"] = str(self.window.window_name)
        if target is not None:
            extra["tmux_target"] = str(target)

        logger.info("pane created", extra=extra)

        return pane

    """
    Commands (helpers)
    """

    def set_width(self, width: int) -> Pane:
        """Set pane width.

        Parameters
        ----------
        width : int
            Pane width, in cells.

        Returns
        -------
        :class:`Pane`
            Self, for method chaining.
        """
        self.resize(width=width)
        return self

    def set_height(self, height: int) -> Pane:
        """Set pane height.

        Parameters
        ----------
        height : int
            Pane height, in cells.

        Returns
        -------
        :class:`Pane`
            Self, for method chaining.
        """
        self.resize(height=height)
        return self

    def set_title(self, title: str) -> Pane:
        """Set pane title via ``select-pane -T``.

        Parameters
        ----------
        title : str
            Title to set for the pane.

        Returns
        -------
        :class:`Pane`
            The pane instance, for method chaining.

        Examples
        --------
        >>> pane.set_title('my-title')
        Pane(...)

        >>> pane.pane_title
        'my-title'
        """
        proc = self.cmd("select-pane", "-T", title)
        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)
        self.refresh()
        return self

    def enter(self) -> Pane:
        """Send carriage return to pane.

        ``$ tmux send-keys`` send Enter to the pane.
        """
        self.cmd("send-keys", "Enter")
        return self

    def display_popup(
        self,
        command: str | None = None,
        *,
        close_on_exit: bool | None = None,
        close_on_success: bool | None = None,
        close_existing: bool | None = None,
        width: int | str | None = None,
        height: int | str | None = None,
        x: int | str | None = None,
        y: int | str | None = None,
        start_directory: StrPath | None = None,
        title: str | None = None,
        border_lines: str | None = None,
        style: str | None = None,
        border_style: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> None:
        """Display a popup overlay via ``$ tmux display-popup``.

        Requires tmux 3.2+ and an attached client. Use
        :class:`~libtmux._internal.control_mode.ControlMode` in tests to provide
        a client.

        Parameters
        ----------
        command : str, optional
            Shell command to run in the popup.
        close_on_exit : bool, optional
            Close popup when command exits (``-E`` flag).
        close_on_success : bool, optional
            Close popup only on success exit code (``-EE`` flag, passing ``-E``
            twice).
        close_existing : bool, optional
            Close any existing popup on the client (``-C`` flag).
        width : int or str, optional
            Popup width (``-w`` flag).
        height : int or str, optional
            Popup height (``-h`` flag).
        x : int or str, optional
            Popup x position (``-x`` flag).
        y : int or str, optional
            Popup y position (``-y`` flag).
        start_directory : str or PathLike, optional
            Working directory (``-d`` flag).
        title : str, optional
            Popup title (``-T`` flag). Requires tmux 3.3+.
        border_lines : str, optional
            Border line style (``-b`` flag). Requires tmux 3.3+.
        style : str, optional
            Popup style (``-s`` flag). Requires tmux 3.3+.
        border_style : str, optional
            Border style (``-S`` flag). Requires tmux 3.3+.
        environment : dict, optional
            Environment variables (``-e`` flag). Requires tmux 3.3+.

        .. versionadded:: 0.45

        Examples
        --------
        Not directly testable — popup rendering requires a TTY-backed client.
        Control-mode provides an attached client for invocation but the popup
        itself is not visible or verifiable.

        >>> with control_mode() as ctl:
        ...     pane.display_popup(command='true', close_on_exit=True)
        """
        import warnings

        from libtmux.common import has_gte_version

        tmux_args: tuple[str, ...] = ()

        if close_existing:
            tmux_args += ("-C",)

        if close_on_exit and close_on_success:
            msg = (
                "close_on_exit and close_on_success are mutually exclusive: "
                "use close_on_exit=True for -E (close on any exit) "
                "or close_on_success=True for -EE (close on zero exit code only)"
            )
            raise ValueError(msg)

        if close_on_exit:
            tmux_args += ("-E",)

        if close_on_success:
            tmux_args += ("-E", "-E")

        if width is not None:
            tmux_args += ("-w", str(width))

        if height is not None:
            tmux_args += ("-h", str(height))

        if x is not None:
            tmux_args += ("-x", str(x))

        if y is not None:
            tmux_args += ("-y", str(y))

        if start_directory is not None:
            start_path = pathlib.Path(start_directory).expanduser()
            tmux_args += ("-d", str(start_path))

        if title is not None:
            if has_gte_version("3.3", tmux_bin=self.server.tmux_bin):
                tmux_args += ("-T", title)
            else:
                warnings.warn(
                    "title requires tmux 3.3+, ignoring",
                    stacklevel=2,
                )

        if border_lines is not None:
            if has_gte_version("3.3", tmux_bin=self.server.tmux_bin):
                tmux_args += ("-b", border_lines)
            else:
                warnings.warn(
                    "border_lines requires tmux 3.3+, ignoring",
                    stacklevel=2,
                )

        if style is not None:
            if has_gte_version("3.3", tmux_bin=self.server.tmux_bin):
                tmux_args += ("-s", style)
            else:
                warnings.warn(
                    "style requires tmux 3.3+, ignoring",
                    stacklevel=2,
                )

        if border_style is not None:
            if has_gte_version("3.3", tmux_bin=self.server.tmux_bin):
                tmux_args += ("-S", border_style)
            else:
                warnings.warn(
                    "border_style requires tmux 3.3+, ignoring",
                    stacklevel=2,
                )

        if environment:
            if has_gte_version("3.3", tmux_bin=self.server.tmux_bin):
                for k, v in environment.items():
                    tmux_args += (f"-e{k}={v}",)
            else:
                warnings.warn(
                    "environment requires tmux 3.3+, ignoring",
                    stacklevel=2,
                )

        if command is not None:
            tmux_args += (command,)

        proc = self.cmd("display-popup", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def paste_buffer(
        self,
        *,
        buffer_name: str | None = None,
        delete_after: bool | None = None,
        linefeed_separator: bool | None = None,
        bracket: bool | None = None,
        separator: str | None = None,
    ) -> None:
        """Paste a buffer into the pane via ``$ tmux paste-buffer``.

        Parameters
        ----------
        buffer_name : str, optional
            Name of the buffer to paste (``-b`` flag).
        delete_after : bool, optional
            Delete the buffer after pasting (``-d`` flag).
        linefeed_separator : bool, optional
            Use newline as the line separator instead of carriage return
            (``-r`` flag).
        bracket : bool, optional
            Use bracketed paste mode (``-p`` flag).
        separator : str, optional
            Separator between lines (``-s`` flag).

        Examples
        --------
        >>> server.set_buffer('pasted_text')
        >>> pane.paste_buffer()
        """
        tmux_args: tuple[str, ...] = ()

        if delete_after:
            tmux_args += ("-d",)

        if linefeed_separator:
            tmux_args += ("-r",)

        if bracket:
            tmux_args += ("-p",)

        if buffer_name is not None:
            tmux_args += ("-b", buffer_name)

        if separator is not None:
            tmux_args += ("-s", separator)

        proc = self.cmd("paste-buffer", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def pipe(
        self,
        command: str | None = None,
        *,
        output_only: bool | None = None,
        input_only: bool | None = None,
        toggle: bool | None = None,
    ) -> None:
        """Pipe pane output to a shell command via ``$ tmux pipe-pane``.

        Parameters
        ----------
        command : str, optional
            Shell command to pipe to. If None, stops piping.
        output_only : bool, optional
            Only pipe output from the pane (``-O`` flag).
        input_only : bool, optional
            Only pipe input to the pane (``-I`` flag).
        toggle : bool, optional
            Toggle piping on/off (``-o`` flag).

        Examples
        --------
        >>> pane.pipe('cat >> /tmp/output.txt')

        Stop piping:

        >>> pane.pipe()
        """
        tmux_args: tuple[str, ...] = ()

        if output_only:
            tmux_args += ("-O",)

        if input_only:
            tmux_args += ("-I",)

        if toggle:
            tmux_args += ("-o",)

        if command is not None:
            tmux_args += (command,)

        proc = self.cmd("pipe-pane", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def copy_mode(
        self,
        *,
        scroll_up: bool | None = None,
        exit_on_bottom: bool | None = None,
        mouse_drag: bool | None = None,
        cancel: bool | None = None,
    ) -> None:
        """Enter copy mode via ``$ tmux copy-mode``.

        Parameters
        ----------
        scroll_up : bool, optional
            Start scrolled up one page (``-u`` flag).
        exit_on_bottom : bool, optional
            Exit copy mode when scrolling reaches the bottom of the
            history (``-e`` flag).
        mouse_drag : bool, optional
            Start mouse drag (``-M`` flag).
        cancel : bool, optional
            Cancel copy mode and any other modes (``-q`` flag).

        Examples
        --------
        >>> pane.copy_mode()

        Exit copy mode:

        >>> pane.send_keys('q')
        """
        tmux_args: tuple[str, ...] = ()

        if scroll_up:
            tmux_args += ("-u",)

        if exit_on_bottom:
            tmux_args += ("-e",)

        if mouse_drag:
            tmux_args += ("-M",)

        if cancel:
            tmux_args += ("-q",)

        proc = self.cmd("copy-mode", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def clock_mode(self) -> None:
        """Enter clock mode via ``$ tmux clock-mode``.

        Examples
        --------
        >>> pane.clock_mode()

        Exit clock mode:

        >>> pane.send_keys('q')
        """
        proc = self.cmd("clock-mode")

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def display_panes(
        self,
        *,
        duration: int | None = None,
        no_select: bool | None = None,
    ) -> None:
        """Show pane numbers via ``$ tmux display-panes``.

        Requires an attached client.

        Parameters
        ----------
        duration : int, optional
            Duration in milliseconds to display pane numbers (``-d`` flag).
        no_select : bool, optional
            Do not select a pane on keypress (``-N`` flag).

        Examples
        --------
        >>> with control_mode() as ctl:
        ...     window.active_pane.display_panes()
        """
        tmux_args: tuple[str, ...] = ()

        if duration is not None:
            tmux_args += ("-d", str(duration))

        if no_select:
            tmux_args += ("-N",)

        proc = self.server.cmd("display-panes", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def choose_buffer(self) -> None:
        """Enter buffer chooser via ``$ tmux choose-buffer``.

        Examples
        --------
        >>> pane.choose_buffer()
        """
        proc = self.cmd("choose-buffer")

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def choose_client(self) -> None:
        """Enter client chooser via ``$ tmux choose-client``.

        Examples
        --------
        >>> pane.choose_client()
        """
        proc = self.cmd("choose-client")

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def choose_tree(
        self,
        *,
        sessions_collapsed: bool | None = None,
        windows_collapsed: bool | None = None,
    ) -> None:
        """Enter tree chooser via ``$ tmux choose-tree``.

        Parameters
        ----------
        sessions_collapsed : bool, optional
            Start with sessions collapsed (``-s`` flag).
        windows_collapsed : bool, optional
            Start with windows collapsed (``-w`` flag).

        Examples
        --------
        >>> pane.choose_tree()
        """
        tmux_args: tuple[str, ...] = ()

        if sessions_collapsed:
            tmux_args += ("-s",)

        if windows_collapsed:
            tmux_args += ("-w",)

        proc = self.cmd("choose-tree", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def customize_mode(self) -> None:
        """Enter customize mode via ``$ tmux customize-mode``.

        Examples
        --------
        >>> pane.customize_mode()
        """
        proc = self.cmd("customize-mode")

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def find_window(
        self,
        match_string: str,
        *,
        match_content: bool | None = None,
        case_insensitive: bool | None = None,
        match_name: bool | None = None,
        regex: bool | None = None,
        match_title: bool | None = None,
    ) -> None:
        """Search for a window matching a string via ``$ tmux find-window``.

        Opens a choose-tree filtered to matching windows.

        Parameters
        ----------
        match_string : str
            String to search for in window names, titles, and content.
        match_content : bool, optional
            Match visible pane content (``-C`` flag).
        case_insensitive : bool, optional
            Case-insensitive matching (``-i`` flag).
        match_name : bool, optional
            Match window name only (``-N`` flag).
        regex : bool, optional
            Treat match string as a regex (``-r`` flag).
        match_title : bool, optional
            Match pane title (``-T`` flag).

        Examples
        --------
        >>> pane.find_window('sh')
        """
        tmux_args: tuple[str, ...] = ()

        if match_content:
            tmux_args += ("-C",)

        if case_insensitive:
            tmux_args += ("-i",)

        if match_name:
            tmux_args += ("-N",)

        if regex:
            tmux_args += ("-r",)

        if match_title:
            tmux_args += ("-T",)

        tmux_args += (match_string,)

        proc = self.cmd("find-window", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def send_prefix(self, *, secondary: bool | None = None) -> None:
        """Send the prefix key to the pane via ``$ tmux send-prefix``.

        Parameters
        ----------
        secondary : bool, optional
            Send the secondary prefix key (``-2`` flag).

        Examples
        --------
        >>> pane.send_prefix()
        """
        tmux_args: tuple[str, ...] = ()

        if secondary:
            tmux_args += ("-2",)

        proc = self.cmd("send-prefix", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def respawn(
        self,
        *,
        shell: str | None = None,
        start_directory: StrPath | None = None,
        environment: dict[str, str] | None = None,
        kill: bool | None = None,
    ) -> None:
        """Respawn the pane process via ``$ tmux respawn-pane``.

        Parameters
        ----------
        shell : str, optional
            Shell command to run in the respawned pane.
        start_directory : str or PathLike, optional
            Working directory for the respawned pane (``-c`` flag).
        environment : dict, optional
            Environment variables (``-e`` flag).
        kill : bool, optional
            Kill the current process before respawning (``-k`` flag).
            Required if the pane is still active.

        Examples
        --------
        >>> pane = window.split(shell='sleep 1m')
        >>> pane.respawn(kill=True, shell='sh')
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

        proc = self.cmd("respawn-pane", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def move(
        self,
        target: str | Pane | Window,
        *,
        vertical: bool = True,
        detach: bool = True,
        full_window: bool | None = None,
        size: str | int | None = None,
        before: bool | None = None,
    ) -> None:
        """Move this pane to another window via ``$ tmux move-pane``.

        Similar to :meth:`join` but invokes the ``move-pane`` command directly.

        Parameters
        ----------
        target : str, Pane, or Window
            Target pane or window to move into.
        vertical : bool, optional
            Split vertically (``-v`` flag), default True. False for
            horizontal (``-h``).
        detach : bool, optional
            Do not switch to the target window (``-d`` flag), default True.
        full_window : bool, optional
            Use the full window width/height (``-f`` flag).
        size : str or int, optional
            Size for the moved pane (``-l`` flag).
        before : bool, optional
            Place the pane before the target (``-b`` flag).

        Examples
        --------
        >>> pane_to_move = window.split(shell='sleep 1m')
        >>> w2 = session.new_window(window_name='move_target')
        >>> pane_to_move.move(w2)
        """
        tmux_args: tuple[str, ...] = ()

        if vertical:
            tmux_args += ("-v",)
        else:
            tmux_args += ("-h",)

        if detach:
            tmux_args += ("-d",)

        if full_window:
            tmux_args += ("-f",)

        if size is not None:
            tmux_args += (f"-l{size}",)

        if before:
            tmux_args += ("-b",)

        # Determine target ID
        from libtmux.window import Window

        if isinstance(target, Pane):
            target_id = str(target.pane_id)
        elif isinstance(target, Window):
            target_id = str(target.window_id)
        else:
            target_id = target

        tmux_args += ("-s", str(self.pane_id), "-t", target_id)

        proc = self.server.cmd("move-pane", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def join(
        self,
        target: str | Pane | Window,
        *,
        vertical: bool = True,
        detach: bool = True,
        full_window: bool | None = None,
        size: str | int | None = None,
        before: bool | None = None,
    ) -> None:
        """Join this pane into another window/pane via ``$ tmux join-pane``.

        This is the inverse of :meth:`break_pane`.

        Parameters
        ----------
        target : str, Pane, or Window
            Target pane or window to join into.
        vertical : bool, optional
            Join vertically (``-v`` flag), default True. Set to False for
            horizontal (``-h``).
        detach : bool, optional
            Do not switch to the target window (``-d`` flag), default True.
        full_window : bool, optional
            Join spanning the full window width/height (``-f`` flag).
        size : str or int, optional
            Size for the joined pane (``-l`` flag).
        before : bool, optional
            Place the pane before the target (``-b`` flag).

        Examples
        --------
        >>> pane_to_join = window.split(shell='sleep 1m')
        >>> new_window = pane_to_join.break_pane()
        >>> pane_to_join.join(window)
        """
        tmux_args: tuple[str, ...] = ()

        if vertical:
            tmux_args += ("-v",)
        else:
            tmux_args += ("-h",)

        if detach:
            tmux_args += ("-d",)

        if full_window:
            tmux_args += ("-f",)

        if size is not None:
            tmux_args += (f"-l{size}",)

        if before:
            tmux_args += ("-b",)

        # Determine target ID
        from libtmux.window import Window

        if isinstance(target, Pane):
            target_id = str(target.pane_id)
        elif isinstance(target, Window):
            target_id = str(target.window_id)
        else:
            target_id = target

        tmux_args += ("-s", str(self.pane_id), "-t", target_id)

        # Use server.cmd to avoid auto-adding -t from self.cmd
        proc = self.server.cmd("join-pane", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def break_pane(
        self,
        *,
        detach: bool = True,
        window_name: str | None = None,
    ) -> Window:
        """Break this pane out into a new window via ``$ tmux break-pane``.

        Parameters
        ----------
        detach : bool, optional
            Do not switch to the new window (``-d`` flag), default True.
        window_name : str, optional
            Name for the new window (``-n`` flag).

        Returns
        -------
        :class:`Window`
            The newly created window containing the pane.

        Examples
        --------
        >>> pane_to_break = window.split(shell='sleep 1m')
        >>> new_window = pane_to_break.break_pane(window_name='broken')
        >>> new_window.window_name
        'broken'
        """
        tmux_args: tuple[str, ...] = ("-P", "-F#{window_id}")

        if detach:
            tmux_args += ("-d",)

        if window_name is not None:
            tmux_args += ("-n", window_name)

        tmux_args += ("-s", str(self.pane_id))

        # Use server.cmd to avoid auto-adding -t from self.cmd
        proc = self.server.cmd("break-pane", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

        window_id = proc.stdout[0].strip()

        from libtmux.window import Window

        return Window.from_window_id(server=self.server, window_id=window_id)

    def swap(
        self,
        target: str | Pane,
        *,
        detach: bool | None = None,
        move_up: bool | None = None,
        move_down: bool | None = None,
        keep_zoom: bool | None = None,
    ) -> None:
        """Swap this pane with another via ``$ tmux swap-pane``.

        Parameters
        ----------
        target : str or Pane
            Target pane to swap with. Can be a pane ID string or Pane object.
        detach : bool, optional
            Do not change the active pane (``-d`` flag).
        move_up : bool, optional
            Swap with the pane above (``-U`` flag). Overrides *target*.
        move_down : bool, optional
            Swap with the pane below (``-D`` flag). Overrides *target*.
        keep_zoom : bool, optional
            Keep the window zoomed if it was zoomed (``-Z`` flag).

        Examples
        --------
        >>> pane1 = window.active_pane
        >>> pane2 = window.split()
        >>> pane1_id, pane2_id = pane1.pane_id, pane2.pane_id
        >>> pane1.swap(pane2)
        >>> pane1.refresh()
        >>> pane2.refresh()
        """
        tmux_args: tuple[str, ...] = ()

        if detach:
            tmux_args += ("-d",)

        if move_up:
            tmux_args += ("-U",)

        if move_down:
            tmux_args += ("-D",)

        if keep_zoom:
            tmux_args += ("-Z",)

        target_id = target.pane_id if isinstance(target, Pane) else target
        tmux_args += ("-s", str(target_id))

        proc = self.cmd("swap-pane", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def clear_history(self, *, reset_hyperlinks: bool | None = None) -> None:
        """Clear pane history buffer via ``$ tmux clear-history``.

        Parameters
        ----------
        reset_hyperlinks : bool, optional
            Also reset hyperlinks (``-H`` flag). Requires tmux 3.4+.

            .. versionadded:: 0.45

        Examples
        --------
        >>> pane.clear_history()
        """
        import warnings

        from libtmux.common import has_gte_version

        tmux_args: tuple[str, ...] = ()

        if reset_hyperlinks:
            if has_gte_version("3.4", tmux_bin=self.server.tmux_bin):
                tmux_args += ("-H",)
            else:
                warnings.warn(
                    "reset_hyperlinks requires tmux 3.4+, ignoring",
                    stacklevel=2,
                )

        proc = self.cmd("clear-history", *tmux_args)

        if proc.stderr:
            raise exc.LibTmuxException(proc.stderr)

    def clear(self) -> Pane:
        """Clear pane."""
        self.send_keys("reset")
        return self

    def reset(self) -> Pane:
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
    def id(self) -> str | None:
        """Alias of :attr:`Pane.pane_id`.

        >>> pane.id
        '%1'

        >>> pane.id == pane.pane_id
        True
        """
        return self.pane_id

    @property
    def index(self) -> str | None:
        """Alias of :attr:`Pane.pane_index`.

        >>> pane.index
        '0'

        >>> pane.index == pane.pane_index
        True
        """
        return self.pane_index

    @property
    def height(self) -> str | None:
        """Alias of :attr:`Pane.pane_height`.

        >>> pane.height.isdigit()
        True

        >>> pane.height == pane.pane_height
        True
        """
        return self.pane_height

    @property
    def width(self) -> str | None:
        """Alias of :attr:`Pane.pane_width`.

        >>> pane.width.isdigit()
        True

        >>> pane.width == pane.pane_width
        True
        """
        return self.pane_width

    @property
    def title(self) -> str | None:
        """Alias for :attr:`pane_title`.

        >>> pane.set_title('test-alias')
        Pane(...)

        >>> pane.title == pane.pane_title
        True
        """
        return self.pane_title

    @property
    def at_top(self) -> bool:
        """Typed, converted wrapper around :attr:`Pane.pane_at_top`.

        >>> pane.pane_at_top
        '1'

        >>> pane.at_top
        True
        """
        return self.pane_at_top == "1"

    @property
    def at_bottom(self) -> bool:
        """Typed, converted wrapper around :attr:`Pane.pane_at_bottom`.

        >>> pane.pane_at_bottom
        '1'

        >>> pane.at_bottom
        True
        """
        return self.pane_at_bottom == "1"

    @property
    def at_left(self) -> bool:
        """Typed, converted wrapper around :attr:`Pane.pane_at_left`.

        >>> pane.pane_at_left
        '1'

        >>> pane.at_left
        True
        """
        return self.pane_at_left == "1"

    @property
    def at_right(self) -> bool:
        """Typed, converted wrapper around :attr:`Pane.pane_at_right`.

        >>> pane.pane_at_right
        '1'

        >>> pane.at_right
        True
        """
        return self.pane_at_right == "1"

    #
    # Legacy: Redundant stuff we want to remove
    #
    def split_window(
        self,
        target: int | str | None = None,
        attach: bool = False,
        start_directory: StrPath | None = None,
        vertical: bool = True,
        shell: str | None = None,
        size: str | int | None = None,
        percent: int | None = None,  # deprecated
        environment: dict[str, str] | None = None,
    ) -> Pane:  # New Pane, not self
        """Split window at pane and return newly created :class:`Pane`.

        Parameters
        ----------
        attach : bool, optional
            Attach / select pane after creation.
        start_directory : str or PathLike, optional
            specifies the working directory in which the new pane is created.
        vertical : bool, optional
            split vertically
        percent: int, optional
            percentage to occupy with respect to current pane
        environment: dict, optional
            Environmental variables for new pane. Passthrough to ``-e``.

        Notes
        -----
        .. deprecated:: 0.33

           Deprecated in favor of :meth:`.split`.
        """
        raise exc.DeprecatedError(
            deprecated="Pane.split_window()",
            replacement="Pane.split()",
            version="0.33.0",
        )

    def get(self, key: str, default: t.Any | None = None) -> t.Any:
        """Return key-based lookup. Deprecated by attributes.

        .. deprecated:: 0.17

           Deprecated by attribute lookup, e.g. ``pane['window_name']`` is now
           accessed via ``pane.window_name``.

        """
        raise exc.DeprecatedError(
            deprecated="Pane.get()",
            replacement="direct attribute access (e.g., pane.pane_id)",
            version="0.17.0",
        )

    def __getitem__(self, key: str) -> t.Any:
        """Return item lookup by key. Deprecated in favor of attributes.

        .. deprecated:: 0.17

           Deprecated in favor of attributes. e.g. ``pane['window_name']`` is now
           accessed via ``pane.window_name``.

        """
        raise exc.DeprecatedError(
            deprecated="Pane[key] lookup",
            replacement="direct attribute access (e.g., pane.pane_id)",
            version="0.17.0",
        )

    def resize_pane(
        self,
        # Adjustments
        adjustment_direction: ResizeAdjustmentDirection | None = None,
        adjustment: int | None = None,
        # Manual
        height: str | int | None = None,
        width: str | int | None = None,
        # Zoom
        zoom: bool | None = None,
        # Mouse
        mouse: bool | None = None,
        # Optional flags
        trim_below: bool | None = None,
    ) -> Pane:
        """Resize pane, deprecated by :meth:`Pane.resize`.

        .. deprecated:: 0.28

           Deprecated by :meth:`Pane.resize`.
        """
        raise exc.DeprecatedError(
            deprecated="Pane.resize_pane()",
            replacement="Pane.resize()",
            version="0.28.0",
        )
