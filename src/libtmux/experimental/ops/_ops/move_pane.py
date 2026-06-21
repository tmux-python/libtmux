"""The ``move-pane`` operation (dual-target)."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._ops.join_pane import JoinPane
from libtmux.experimental.ops.registry import register


@register
@dataclass(frozen=True, kw_only=True)
class MovePane(JoinPane):
    """Move a source pane into a destination window (``move-pane``).

    Identical in shape to :class:`JoinPane`; tmux exposes ``move-pane`` as the
    same command under a different name.

    Examples
    --------
    >>> from libtmux.experimental.ops._types import PaneId, WindowId
    >>> MovePane(target=WindowId("@1"), src_target=PaneId("%2")).render()
    ('move-pane', '-t', '@1', '-v', '-d', '-s', '%2')
    """

    kind = "move_pane"
    command = "move-pane"
