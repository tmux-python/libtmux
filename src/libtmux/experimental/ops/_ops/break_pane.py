"""The ``break-pane`` operation (creates a window, captures its id)."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import CreateResult

if t.TYPE_CHECKING:
    from libtmux.experimental.ops._types import Status


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

    Examples
    --------
    >>> from libtmux.experimental.ops._types import PaneId
    >>> BreakPane(src_target=PaneId("%2"), name="logs").render()
    ('break-pane', '-d', '-n', 'logs', '-P', '-F', '#{window_id}', '-s', '%2')
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
