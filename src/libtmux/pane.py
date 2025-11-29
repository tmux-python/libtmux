"""Pythonization of the :ref:`tmux(1)` pane.

libtmux.pane
~~~~~~~~~~~~

"""

from __future__ import annotations

import dataclasses
import logging
import pathlib
import typing as t
import warnings

from libtmux import exc
from libtmux.common import AsyncTmuxCmd, has_gte_version, has_lt_version, tmux_cmd
from libtmux.constants import (
    PANE_DIRECTION_FLAG_MAP,
    RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP,
    PaneDirection,
    ResizeAdjustmentDirection,
)
from libtmux.formats import FORMAT_SEPARATOR
from libtmux.neo import Obj, fetch_obj

__all__ = ["Pane", "PaneDirection"]


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

    async def acmd(
        self,
        cmd: str,
        *args: t.Any,
        target: str | int | None = None,
    ) -> AsyncTmuxCmd:
        """Execute tmux subcommand within pane context.

        Automatically binds target by adding  ``-t`` for object's pane ID to the
        command. Pass ``target`` to keyword arguments to override.

        Examples
        --------
        >>> import asyncio
        >>> async def test_acmd():
        ...     result = await pane.acmd('split-window', '-P')
        ...     print(result.stdout[0])
        >>> asyncio.run(test_acmd())
        libtmux...:...

        From raw output to an enriched `Pane` object:

        >>> async def test_from_pane():
        ...     pane_id_result = await pane.acmd(
        ...         'split-window', '-P', '-F#{pane_id}'
        ...     )
        ...     return Pane.from_pane_id(
        ...         pane_id=pane_id_result.stdout[0],
        ...         server=session.server
        ...     )
        >>> asyncio.run(test_from_pane())
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

        return await self.server.acmd(cmd, *args, target=target)

    async def asend_keys(
        self,
        cmd: str,
        enter: bool | None = True,
        suppress_history: bool | None = False,
        literal: bool | None = False,
    ) -> None:
        r"""``$ tmux send-keys`` to the pane asynchronously.

        This is the async version of :meth:`send_keys`. It uses ``await self.acmd()``
        for non-blocking command execution, making it suitable for async applications
        and enabling concurrent command execution across multiple panes.

        A leading space character is added to cmd to avoid polluting the
        user's history when suppress_history is True.

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

        See Also
        --------
        :meth:`send_keys` : Synchronous version of this method
        :meth:`acapture_pane` : Capture pane output asynchronously
        :meth:`acmd` : Execute arbitrary tmux commands asynchronously

        Notes
        -----
        This method is non-blocking and suitable for use in async applications.
        It's particularly powerful when sending commands to multiple panes concurrently
        using ``asyncio.gather()``, which can significantly improve performance
        compared to sequential execution.

        .. versionadded:: 0.48.0

            Added async send_keys support.

        Examples
        --------
        Basic command execution:

        >>> import asyncio
        >>> async def test_basic_send():
        ...     test_session = await server.anew_session("asend_basic")
        ...     pane = test_session.active_pane
        ...     await pane.asend_keys('echo "Hello world"', enter=True)
        ...     # Wait a moment for command to execute
        ...     await asyncio.sleep(0.1)
        ...     output = pane.capture_pane()
        ...     has_hello = any("Hello world" in line for line in output)
        ...     await server.acmd("kill-session", target="asend_basic")
        ...     return has_hello
        >>> asyncio.run(test_basic_send())
        True

        Send without enter:

        >>> import asyncio
        >>> async def test_no_enter():
        ...     test_session = await server.anew_session("asend_no_enter")
        ...     pane = test_session.active_pane
        ...     await pane.asend_keys('echo test', enter=False)
        ...     await server.acmd("kill-session", target="asend_no_enter")
        ...     # Command sent but not executed (no enter)
        >>> asyncio.run(test_no_enter())

        Literal mode (special characters sent as-is):

        >>> import asyncio
        >>> async def test_literal():
        ...     test_session = await server.anew_session("asend_literal")
        ...     pane = test_session.active_pane
        ...     await pane.asend_keys('C-c', literal=True, enter=False)
        ...     await server.acmd("kill-session", target="asend_literal")
        ...     # Sends literal "C-c" text, not Ctrl-C signal
        >>> asyncio.run(test_literal())

        Concurrent command execution across multiple panes:

        >>> import asyncio
        >>> async def test_concurrent_send():
        ...     test_session = await server.anew_session("asend_concurrent")
        ...     window = test_session.active_window
        ...     pane1 = window.active_pane
        ...     pane2 = window.split()
        ...     pane3 = window.split()
        ...     # Send commands to all panes concurrently
        ...     await asyncio.gather(
        ...         pane1.asend_keys('echo pane1'),
        ...         pane2.asend_keys('echo pane2'),
        ...         pane3.asend_keys('echo pane3'),
        ...     )
        ...     await server.acmd("kill-session", target="asend_concurrent")
        ...     # All three commands sent in parallel
        >>> asyncio.run(test_concurrent_send())
        """
        prefix = " " if suppress_history else ""

        if literal:
            await self.acmd("send-keys", "-l", prefix + cmd)
        else:
            await self.acmd("send-keys", prefix + cmd)

        if enter:
            await self.acmd("send-keys", "Enter")

    async def acapture_pane(
        self,
        start: t.Literal["-"] | int | None = None,
        end: t.Literal["-"] | int | None = None,
    ) -> str | list[str]:
        """Capture text from pane asynchronously.

        This is the async version of :meth:`capture_pane`. It uses ``await self.acmd()``
        for non-blocking output capture, making it suitable for async applications
        and enabling concurrent output capture from multiple panes.

        ``$ tmux capture-pane`` to pane.
        ``$ tmux capture-pane -S -10`` to pane.
        ``$ tmux capture-pane -E 3`` to pane.
        ``$ tmux capture-pane -S - -E -`` to pane.

        Parameters
        ----------
        start : str or int, optional
            Specify the starting line number.
            - Zero is the first line of the visible pane
            - Positive numbers are lines in the visible pane
            - Negative numbers are lines in the history
            - ``"-"`` is the start of the history
            Default: None (capture visible pane only)
        end : str or int, optional
            Specify the ending line number.
            - Zero is the first line of the visible pane
            - Positive numbers are lines in the visible pane
            - Negative numbers are lines in the history
            - ``"-"`` is the end of the visible pane
            Default: None (capture to end of visible pane)

        Returns
        -------
        str or list[str]
            Captured pane content

        See Also
        --------
        :meth:`capture_pane` : Synchronous version of this method
        :meth:`asend_keys` : Send keys to pane asynchronously
        :meth:`acmd` : Execute arbitrary tmux commands asynchronously

        Notes
        -----
        This method is non-blocking and suitable for async applications. It is
        especially helpful when capturing output from multiple panes concurrently
        via ``asyncio.gather()``, which can significantly improve performance
        compared to sequential capture.

        .. versionadded:: 0.48.0

            Added async capture_pane support.

        Examples
        --------
        Basic pane output capture:

        >>> import asyncio
        >>> async def test_basic_capture():
        ...     test_session = await server.anew_session("acapture_basic")
        ...     pane = test_session.active_pane
        ...     await pane.asend_keys('echo "Test output"')
        ...     await asyncio.sleep(0.1)
        ...     output = await pane.acapture_pane()
        ...     has_test = any("Test output" in line for line in output)
        ...     await server.acmd("kill-session", target="acapture_basic")
        ...     return has_test
        >>> asyncio.run(test_basic_capture())
        True

        Capture with line range:

        >>> import asyncio
        >>> async def test_range_capture():
        ...     test_session = await server.anew_session("acapture_range")
        ...     pane = test_session.active_pane
        ...     # Send multiple lines
        ...     await pane.asend_keys('echo line1')
        ...     await pane.asend_keys('echo line2')
        ...     await pane.asend_keys('echo line3')
        ...     await asyncio.sleep(0.1)
        ...     # Capture last 5 lines
        ...     output = await pane.acapture_pane(start=-5, end="-")
        ...     is_list = isinstance(output, list)
        ...     await server.acmd("kill-session", target="acapture_range")
        ...     return is_list
        >>> asyncio.run(test_range_capture())
        True

        Concurrent output capture from multiple panes:

        >>> import asyncio
        >>> async def test_concurrent_capture():
        ...     test_session = await server.anew_session("acapture_concurrent")
        ...     window = test_session.active_window
        ...     pane1 = window.active_pane
        ...     pane2 = window.split()
        ...     pane3 = window.split()
        ...     # Send commands to all panes
        ...     await asyncio.gather(
        ...         pane1.asend_keys('echo output1'),
        ...         pane2.asend_keys('echo output2'),
        ...         pane3.asend_keys('echo output3'),
        ...     )
        ...     await asyncio.sleep(0.1)
        ...     # Capture output from all panes concurrently
        ...     outputs = await asyncio.gather(
        ...         pane1.acapture_pane(),
        ...         pane2.acapture_pane(),
        ...         pane3.acapture_pane(),
        ...     )
        ...     await server.acmd("kill-session", target="acapture_concurrent")
        ...     return len(outputs)
        >>> asyncio.run(test_concurrent_capture())
        3
        """
        cmd_parts: list[str] = ["capture-pane", "-p"]
        if start is not None:
            cmd_parts.extend(["-S", str(start)])
        if end is not None:
            cmd_parts.extend(["-E", str(end)])
        result = await self.acmd(*cmd_parts)
        return result.stdout

    async def asplit(
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
        environment: dict[str, str] | None = None,
    ) -> Pane:
        """Split window asynchronously and return :class:`Pane`.

        This is the async version of :meth:`split`. It uses ``await self.acmd()``
        for non-blocking pane creation, making it suitable for async applications
        and enabling concurrent pane creation.

        By default, splits beneath the current pane.

        Parameters
        ----------
        target : optional
            Optional, custom *target-pane*, used by :meth:`Window.asplit`.
        attach : bool, optional
            Make new pane the current pane after creating it, default False.
        start_directory : str or PathLike, optional
            Working directory in which the new pane is created.
        direction : PaneDirection, optional
            Direction to split: Above, Below (default), Left, or Right.
        full_window_split : bool, optional
            Split across full window width or height, rather than active pane.
        zoom : bool, optional
            Expand pane after creation.
        shell : str, optional
            Execute a command when splitting the pane. The pane will close
            when the command exits.

            .. warning::

                When this command exits, the pane will close. This feature is
                useful for long-running processes where automatic cleanup is desired.
        size : int or str, optional
            Cell/row count or percentage to occupy with respect to current window.
            Examples: ``50`` (50 cells), ``"50%"`` (50 percent).
        environment : dict[str, str], optional
            Environmental variables for new pane.

            .. note::

                Requires tmux 3.0+. On older versions, this parameter is ignored
                with a warning.

        Returns
        -------
        :class:`Pane`
            The newly created pane object

        Raises
        ------
        :exc:`exc.LibTmuxException`
            If tmux command execution fails (e.g., pane too small)

        See Also
        --------
        :meth:`split` : Synchronous version of this method
        :meth:`asend_keys` : Send keys to pane asynchronously
        :meth:`acapture_pane` : Capture pane output asynchronously

        Notes
        -----
        This method is non-blocking and suitable for use in async applications.
        It's particularly powerful when creating multiple panes concurrently
        using ``asyncio.gather()``, which can significantly improve performance
        compared to sequential creation.

        .. versionadded:: 0.48.0

            Added async split_window support.

        Examples
        --------
        Basic horizontal split (default - below current pane):

        >>> import asyncio
        >>> async def test_basic_split():
        ...     test_session = await server.anew_session("asplit_basic")
        ...     pane = test_session.active_pane
        ...     new_pane = await pane.asplit()
        ...     pane_count = len(test_session.active_window.panes)
        ...     await server.acmd("kill-session", target="asplit_basic")
        ...     return pane_count
        >>> asyncio.run(test_basic_split())
        2

        Vertical split with custom directory:

        >>> import asyncio
        >>> async def test_vertical_split():
        ...     test_session = await server.anew_session("asplit_vertical")
        ...     pane = test_session.active_pane
        ...     new_pane = await pane.asplit(
        ...         direction=PaneDirection.Right,
        ...         start_directory='/tmp'
        ...     )
        ...     pane_count = len(test_session.active_window.panes)
        ...     await server.acmd("kill-session", target="asplit_vertical")
        ...     return pane_count
        >>> asyncio.run(test_vertical_split())
        2

        Split with size specification:

        >>> import asyncio
        >>> async def test_split_with_size():
        ...     test_session = await server.anew_session("asplit_size")
        ...     pane = test_session.active_pane
        ...     new_pane = await pane.asplit(size="30%")
        ...     pane_count = len(test_session.active_window.panes)
        ...     await server.acmd("kill-session", target="asplit_size")
        ...     return pane_count
        >>> asyncio.run(test_split_with_size())
        2

        Concurrent multi-pane creation:

        >>> import asyncio
        >>> async def test_concurrent_splits():
        ...     test_session = await server.anew_session("asplit_concurrent")
        ...     window = test_session.active_window
        ...     base_pane = window.active_pane
        ...     # Create multiple panes concurrently
        ...     new_panes = await asyncio.gather(
        ...         base_pane.asplit(direction=PaneDirection.Below),
        ...         base_pane.asplit(direction=PaneDirection.Right),
        ...     )
        ...     pane_count = len(window.panes)
        ...     await server.acmd("kill-session", target="asplit_concurrent")
        ...     return pane_count >= 3
        >>> asyncio.run(test_concurrent_splits())
        True
        """
        tmux_formats = ["#{pane_id}" + FORMAT_SEPARATOR]

        tmux_args: tuple[str, ...] = ()

        if direction:
            tmux_args += tuple(PANE_DIRECTION_FLAG_MAP[direction])
        else:
            tmux_args += tuple(PANE_DIRECTION_FLAG_MAP[PaneDirection.Below])

        if size is not None:
            if has_lt_version("3.1"):
                if isinstance(size, str) and size.endswith("%"):
                    tmux_args += (f"-p{str(size).rstrip('%')}",)
                else:
                    warnings.warn(
                        'Ignored size. Use percent in tmux < 3.1, e.g. "size=50%"',
                        stacklevel=2,
                    )
            else:
                tmux_args += (f"-l{size}",)

        if full_window_split:
            tmux_args += ("-f",)

        if zoom:
            tmux_args += ("-Z",)

        tmux_args += ("-P", "-F{}".format("".join(tmux_formats)))  # output

        if start_directory:
            # as of 2014-02-08 tmux 1.9-dev doesn't expand ~ in new-window -c.
            start_path = pathlib.Path(start_directory).expanduser()
            tmux_args += (f"-c{start_path}",)

        if not attach:
            tmux_args += ("-d",)

        if environment:
            if has_gte_version("3.0"):
                for k, v in environment.items():
                    tmux_args += (f"-e{k}={v}",)
            else:
                logger.warning(
                    "Environment flag ignored, tmux 3.0 or newer required.",
                )

        if shell:
            tmux_args += (shell,)

        pane_cmd = await self.acmd("split-window", *tmux_args, target=target)

        # tmux < 1.7. This is added in 1.7.
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

        return self.from_pane_id(server=self.server, pane_id=pane_formatters["pane_id"])

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
                if isinstance(height, str):
                    if height.endswith("%") and not has_gte_version("3.1"):
                        raise exc.VersionTooLow
                    if not height.isdigit() and not height.endswith("%"):
                        raise exc.RequiresDigitOrPercentage
                tmux_args += (f"-y{height}",)

            if width:
                if isinstance(width, str):
                    if width.endswith("%") and not has_gte_version("3.1"):
                        raise exc.VersionTooLow
                    if not width.isdigit() and not width.endswith("%"):
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
    ) -> str | list[str]:
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

        See Also
        --------
        :meth:`acapture_pane` : Async version of this method
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
        enter: bool | None = True,
        suppress_history: bool | None = False,
        literal: bool | None = False,
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

        See Also
        --------
        :meth:`asend_keys` : Async version of this method

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
        prefix = " " if suppress_history else ""

        if literal:
            self.cmd("send-keys", "-l", prefix + cmd)
        else:
            self.cmd("send-keys", prefix + cmd)

        if enter:
            self.enter()

    @t.overload
    def display_message(
        self,
        cmd: str,
        get_text: t.Literal[True],
    ) -> str | list[str]: ...

    @t.overload
    def display_message(self, cmd: str, get_text: t.Literal[False]) -> None: ...

    def display_message(
        self,
        cmd: str,
        get_text: bool = False,
    ) -> str | list[str] | None:
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

    """
    Commands ("climber"-helpers)

    These are commands that climb to the parent scope's methods with
    additional scoped window info.
    """

    def select(self) -> Pane:
        """Select pane.

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
        proc = self.cmd("select-pane")

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
        warnings.warn(
            "Pane.select_pane() is deprecated in favor of Pane.select()",
            category=DeprecationWarning,
            stacklevel=2,
        )
        assert isinstance(self.pane_id, str)
        pane = self.window.select_pane(self.pane_id)
        if pane is None:
            raise exc.PaneNotFound(pane_id=self.pane_id)
        return pane

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
            Cell/row or percentage to occupy with respect to current window.
        environment: dict, optional
            Environmental variables for new pane. tmux 3.0+ only. Passthrough to ``-e``.

        See Also
        --------
        :meth:`asplit` : Async version of this method

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

        if size is not None:
            if has_lt_version("3.1"):
                if isinstance(size, str) and size.endswith("%"):
                    tmux_args += (f"-p{str(size).rstrip('%')}",)
                else:
                    warnings.warn(
                        'Ignored size. Use percent in tmux < 3.1, e.g. "size=50%"',
                        stacklevel=2,
                    )
            else:
                tmux_args += (f"-l{size}",)

        if full_window_split:
            tmux_args += ("-f",)

        if zoom:
            tmux_args += ("-Z",)

        tmux_args += ("-P", "-F{}".format("".join(tmux_formats)))  # output

        if start_directory:
            # as of 2014-02-08 tmux 1.9-dev doesn't expand ~ in new-window -c.
            start_path = pathlib.Path(start_directory).expanduser()
            tmux_args += (f"-c{start_path}",)

        if not attach:
            tmux_args += ("-d",)

        if environment:
            if has_gte_version("3.0"):
                for k, v in environment.items():
                    tmux_args += (f"-e{k}={v}",)
            else:
                logger.warning(
                    "Environment flag ignored, tmux 3.0 or newer required.",
                )

        if shell:
            tmux_args += (shell,)

        pane_cmd = self.cmd("split-window", *tmux_args, target=target)

        # tmux < 1.7. This is added in 1.7.
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

        return self.from_pane_id(server=self.server, pane_id=pane_formatters["pane_id"])

    """
    Commands (helpers)
    """

    def set_width(self, width: int) -> Pane:
        """Set pane width.

        Parameters
        ----------
        width : int
            pane width, in cells
        """
        self.resize_pane(width=width)
        return self

    def set_height(self, height: int) -> Pane:
        """Set pane height.

        Parameters
        ----------
        height : int
            height of pain, in cells
        """
        self.resize_pane(height=height)
        return self

    def enter(self) -> Pane:
        """Send carriage return to pane.

        ``$ tmux send-keys`` send Enter to the pane.
        """
        self.cmd("send-keys", "Enter")
        return self

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
            Environmental variables for new pane. tmux 3.0+ only. Passthrough to ``-e``.

        Notes
        -----
        .. deprecated:: 0.33

           Deprecated in favor of :meth:`.split`.
        """
        warnings.warn(
            "Pane.split_window() is deprecated in favor of Pane.split()",
            category=DeprecationWarning,
            stacklevel=2,
        )
        if size is None and percent is not None:
            size = f"{str(percent).rstrip('%')}%"
        return self.split(
            target=target,
            attach=attach,
            start_directory=start_directory,
            direction=PaneDirection.Below if vertical else PaneDirection.Right,
            shell=shell,
            size=size,
            environment=environment,
        )

    def get(self, key: str, default: t.Any | None = None) -> t.Any:
        """Return key-based lookup. Deprecated by attributes.

        .. deprecated:: 0.16

           Deprecated by attribute lookup, e.g. ``pane['window_name']`` is now
           accessed via ``pane.window_name``.

        """
        warnings.warn(
            "Pane.get() is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> t.Any:
        """Return item lookup by key. Deprecated in favor of attributes.

        .. deprecated:: 0.16

           Deprecated in favor of attributes. e.g. ``pane['window_name']`` is now
           accessed via ``pane.window_name``.

        """
        warnings.warn(
            f"Item lookups, e.g. pane['{key}'] is deprecated",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return getattr(self, key)

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
        warnings.warn(
            "Deprecated: Use Pane.resize() instead of Pane.resize_pane()",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return self.resize(
            adjustment_direction=adjustment_direction,
            adjustment=adjustment,
            height=height,
            width=width,
            zoom=zoom,
            mouse=mouse,
            trim_below=trim_below,
        )
