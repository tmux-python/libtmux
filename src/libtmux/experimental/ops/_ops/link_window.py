"""The ``link-window`` operation (dual-target)."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class LinkWindow(Operation[AckResult]):
    """Link a window into another session (``link-window``).

    ``target`` is the destination (``-t``); ``src_target`` is the window to
    link (``-s``).

    Parameters
    ----------
    detach : bool
        Do not change the active window (``-d``).
    before, after : bool
        Insert before (``-b``) or after (``-a``) the destination index.
    kill : bool
        Replace (kill) any window already at the destination (``-k``).

    Examples
    --------
    >>> from libtmux.experimental.ops._types import SessionId, WindowId
    >>> LinkWindow(target=SessionId("$0"), src_target=WindowId("@2")).render()
    ('link-window', '-t', '$0', '-s', '@2')
    """

    kind = "link_window"
    command = "link-window"
    scope = "window"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects()

    detach: bool = False
    before: bool = False
    after: bool = False
    kill: bool = False

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the link flags and ``-s`` source."""
        out: list[str] = []
        if self.detach:
            out.append("-d")
        if self.before:
            out.append("-b")
        if self.after:
            out.append("-a")
        if self.kill:
            out.append("-k")
        out.extend(self.src_args())
        return tuple(out)
