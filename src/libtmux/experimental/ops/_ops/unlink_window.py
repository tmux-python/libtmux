"""The ``unlink-window`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class UnlinkWindow(Operation[AckResult]):
    """Unlink a window from a session (``unlink-window``).

    Parameters
    ----------
    kill : bool
        Also destroy the window if it is no longer linked anywhere (``-k``).

    Examples
    --------
    >>> from libtmux.experimental.ops._types import WindowId
    >>> UnlinkWindow(target=WindowId("@1")).render()
    ('unlink-window', '-t', '@1')
    """

    kind = "unlink_window"
    command = "unlink-window"
    scope = "window"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects()

    kill: bool = False

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the optional ``-k`` flag."""
        return ("-k",) if self.kill else ()
