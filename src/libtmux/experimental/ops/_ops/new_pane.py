"""The ``new-pane`` operation (tmux 3.7+ floating panes)."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import SplitWindowResult

if t.TYPE_CHECKING:
    from collections.abc import Mapping

    from libtmux.experimental.ops._types import Status


@register
@dataclass(frozen=True, kw_only=True)
class NewPane(Operation[SplitWindowResult]):
    """Create a floating pane (``new-pane``; tmux 3.7+).

    ``new-pane`` shares ``split-window``'s machinery but floats by default: the
    pane sits above the tiled layout (popup-style, but non-modal) instead of
    becoming a tiled cell. Geometry is *absolute* -- :attr:`width`/:attr:`height`
    set the size (``-x``/``-y``) and :attr:`x`/:attr:`y` set the top-left offset
    (``-X``/``-Y``); each accepts cells (``int``) or a percentage (``str`` like
    ``"50%"``). Omitted position cascades down-right on repeated calls.

    Like :class:`~.split_window.SplitWindow` it reuses
    :class:`~.results.SplitWindowResult`, capturing the new pane id via
    ``-P -F '#{pane_id}'`` so plans, the wrapper, and MCP bind it the same way.

    Rendering against a tmux older than 3.7 raises
    :exc:`~.exc.VersionUnsupported` (this op sets
    :attr:`~.operation.Operation.min_version`).

    Parameters
    ----------
    width : int or str or None
        Floating pane width in cells or ``N%`` (``-x``).
    height : int or str or None
        Floating pane height in cells or ``N%`` (``-y``).
    x : int or str or None
        Absolute x-position (left offset) in cells or ``N%`` (``-X``).
    y : int or str or None
        Absolute y-position (top offset) in cells or ``N%`` (``-Y``).
    zoom : bool
        Zoom the new pane (``-Z``).
    detach : bool
        Do not focus the new pane (``-d``); defaults ``True`` for headless use.
    empty : bool
        Create an empty pane with no command (``-E``).
    start_directory : str or None
        Working directory for the new pane (``-c``).
    environment : Mapping[str, str] or None
        Environment variables for the new pane (``-e``).
    style : str or None
        Content style (``-s``).
    active_border_style : str or None
        Active border style (``-S``).
    inactive_border_style : str or None
        Inactive border style (``-R``).
    message : str or None
        Remain-on-exit message (``-m``).
    shell_command : str or None
        A shell command to run instead of the default shell.
    capture : bool
        Append ``-P -F '#{pane_id}'`` to capture the new pane id.

    Examples
    --------
    >>> from libtmux.experimental.ops._types import PaneId
    >>> NewPane(target=PaneId("%1"), width=80, height=15, x=5, y=3).render()
    ('new-pane', '-t', '%1', '-x80', '-y15', '-X5', '-Y3', '-d', '-P', '-F',
     '#{pane_id}')

    Percentages and zoom render verbatim:

    >>> NewPane(target=PaneId("%1"), width="50%", height="40%", zoom=True).render()
    ('new-pane', '-t', '%1', '-x50%', '-y40%', '-Z', '-d', '-P', '-F', '#{pane_id}')

    Passing ``detach=False`` focuses the new pane (no ``-d``):

    >>> NewPane(target=PaneId("%1"), width=80, height=15, detach=False).render()
    ('new-pane', '-t', '%1', '-x80', '-y15', '-P', '-F', '#{pane_id}')

    Floating panes need tmux 3.7+; an older tmux is refused:

    >>> NewPane(target=PaneId("%1")).render(version="3.6")
    Traceback (most recent call last):
    ...
    libtmux.experimental.ops.exc.VersionUnsupported: operation 'new_pane'
    requires tmux >= 3.7 (have 3.6)

    The created pane id is parsed into the typed result:

    >>> result = NewPane(target=PaneId("%1")).build_result(returncode=0, stdout=("%2",))
    >>> result.new_pane_id
    '%2'
    """

    kind = "new_pane"
    command = "new-pane"
    scope = "window"
    result_cls = SplitWindowResult
    safety = "mutating"
    chainable = False  # captures a new pane id (-P -F); cannot fold into a ; chain
    effects = Effects(creates="pane")
    min_version = "3.7"

    width: int | str | None = None
    height: int | str | None = None
    x: int | str | None = None
    y: int | str | None = None
    zoom: bool = False
    detach: bool = True
    empty: bool = False
    start_directory: str | None = None
    environment: Mapping[str, str] | None = None
    style: str | None = None
    active_border_style: str | None = None
    inactive_border_style: str | None = None
    message: str | None = None
    shell_command: str | None = None
    capture: bool = True

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render ``new-pane`` geometry, style, capture, and shell flags."""
        out: list[str] = []
        if self.width is not None:
            out.append(f"-x{self.width}")
        if self.height is not None:
            out.append(f"-y{self.height}")
        if self.x is not None:
            out.append(f"-X{self.x}")
        if self.y is not None:
            out.append(f"-Y{self.y}")
        if self.zoom:
            out.append("-Z")
        if self.detach:
            out.append("-d")
        if self.start_directory is not None:
            out.append(f"-c{self.start_directory}")
        if self.environment:
            out.extend(f"-e{key}={value}" for key, value in self.environment.items())
        if self.style is not None:
            out.append(f"-s{self.style}")
        if self.active_border_style is not None:
            out.append(f"-S{self.active_border_style}")
        if self.inactive_border_style is not None:
            out.append(f"-R{self.inactive_border_style}")
        if self.message is not None:
            out.append(f"-m{self.message}")
        if self.empty:
            out.append("-E")
        if self.capture:
            out.extend(("-P", "-F", "#{pane_id}"))
        if self.shell_command is not None:
            out.append(self.shell_command)
        return tuple(out)

    def _make_result(
        self,
        argv: tuple[str, ...],
        status: Status,
        returncode: int,
        stdout: tuple[str, ...],
        stderr: tuple[str, ...],
        version: str | None = None,
    ) -> SplitWindowResult:
        """Parse the captured new-pane id into the typed result."""
        new_pane_id = stdout[0].strip() if status == "complete" and stdout else None
        return SplitWindowResult(
            operation=self,
            argv=argv,
            status=status,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            new_pane_id=new_pane_id,
        )
