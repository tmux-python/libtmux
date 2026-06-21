"""The ``select-pane`` operation."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class SelectPane(Operation[AckResult]):
    """Make a pane active, or move/mark the selection.

    Parameters
    ----------
    direction : {"L", "R", "U", "D"} or None
        Move to the pane left/right/above/below the target.
    last : bool
        Select the last (previously active) pane (``-l``).
    mark, unmark : bool
        Set (``-m``) or clear (``-M``) the marked pane.
    zoom : bool
        Keep the window zoomed (``-Z``).
    title : str or None
        Set the pane title (``-T``).

    Examples
    --------
    >>> from libtmux.experimental.ops._types import PaneId
    >>> SelectPane(target=PaneId("%1")).render()
    ('select-pane', '-t', '%1')
    >>> SelectPane(target=PaneId("%2"), direction="L", zoom=True).render()
    ('select-pane', '-t', '%2', '-L', '-Z')
    """

    kind = "select_pane"
    command = "select-pane"
    scope = "pane"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects(idempotent=True)

    direction: t.Literal["L", "R", "U", "D"] | None = None
    last: bool = False
    mark: bool = False
    unmark: bool = False
    zoom: bool = False
    title: str | None = None

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the selection flags."""
        out: list[str] = []
        if self.last:
            out.append("-l")
        if self.direction is not None:
            out.append(f"-{self.direction}")
        if self.mark:
            out.append("-m")
        if self.unmark:
            out.append("-M")
        if self.zoom:
            out.append("-Z")
        if self.title is not None:
            out.extend(("-T", self.title))
        return tuple(out)
