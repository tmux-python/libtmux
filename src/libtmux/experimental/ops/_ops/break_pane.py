"""The ``break-pane`` operation (creates a window, captures its id)."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import CreateResult
from libtmux.neo import _normalize_tmux_version

if t.TYPE_CHECKING:
    from libtmux.experimental.ops._types import Status


def _breaks_without_name(version: str | None) -> bool:
    """Whether this tmux needs a placeholder ``-n`` for a nameless break-pane.

    tmux 3.7 NULL-derefs ``break-pane`` when ``-n`` is absent (fixed upstream
    after 3.7), so exactly 3.7 must be handed a placeholder name.
    """
    if version is None:
        return False
    return _normalize_tmux_version(version) == _normalize_tmux_version("3.7")


@register
@dataclass(frozen=True, kw_only=True)
class BreakPane(Operation[CreateResult]):
    """Break a pane out into a new window (``break-pane``).

    The pane to break is the ``-s`` source (``src_target``); there is no ``-t``.
    By default it appends ``-P -F '#{window_id}'`` so the new window's id is
    captured into :attr:`~.results.CreateResult.new_id`.

    Parameters
    ----------
    detach : bool
        Do not switch to the new window (``-d``).
    name : str or None
        Name for the new window (``-n``).
    capture : bool
        Append ``-P -F '#{window_id}'`` to capture the new window id.

    Notes
    -----
    tmux 3.7 crashes the server on a nameless ``break-pane`` (a NULL-deref fixed
    upstream after 3.7) and ignores ``-n`` when one is given. To survive, exactly
    3.7 is handed a placeholder ``-n`` when no name was requested; a higher layer
    renames the window afterward when a name is wanted.

    Examples
    --------
    >>> from libtmux.experimental.ops._types import PaneId
    >>> BreakPane(src_target=PaneId("%2"), name="logs").render()
    ('break-pane', '-d', '-n', 'logs', '-P', '-F', '#{window_id}', '-s', '%2')

    On exactly tmux 3.7 a nameless break-pane is given a placeholder name; other
    builds render it bare:

    >>> BreakPane(src_target=PaneId("%2")).render(version="3.7")
    ('break-pane', '-d', '-n', 'libtmux', '-P', '-F', '#{window_id}', '-s', '%2')
    >>> BreakPane(src_target=PaneId("%2")).render(version="3.8")
    ('break-pane', '-d', '-P', '-F', '#{window_id}', '-s', '%2')

    >>> BreakPane(src_target=PaneId("%2")).build_result(
    ...     returncode=0, stdout=("@7",)
    ... ).new_id
    '@7'
    """

    kind = "break_pane"
    command = "break-pane"
    scope = "window"
    result_cls = CreateResult
    safety = "mutating"
    chainable = False
    effects = Effects(creates="window")

    detach: bool = True
    name: str | None = None
    capture: bool = True

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the break flags, capture template, and ``-s`` source."""
        out: list[str] = []
        if self.detach:
            out.append("-d")
        if self.name is not None:
            out.extend(("-n", self.name))
        elif _breaks_without_name(version):
            out.extend(("-n", "libtmux"))
        if self.capture:
            out.extend(("-P", "-F", "#{window_id}"))
        out.extend(self.src_args())
        return tuple(out)

    def _make_result(
        self,
        argv: tuple[str, ...],
        status: Status,
        returncode: int,
        stdout: tuple[str, ...],
        stderr: tuple[str, ...],
        version: str | None = None,
    ) -> CreateResult:
        """Parse the captured new-window id."""
        new_id = stdout[0].strip() if status == "complete" and stdout else None
        return CreateResult(
            operation=self,
            argv=argv,
            status=status,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            new_id=new_id,
        )
