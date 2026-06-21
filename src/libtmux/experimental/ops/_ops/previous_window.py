"""The ``previous-window`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class PreviousWindow(Operation[AckResult]):
    """Select the previous window in a session (``previous-window``).

    Parameters
    ----------
    alert : bool
        Move to the previous window with an alert (``-a``).

    Examples
    --------
    >>> from libtmux.experimental.ops._types import SessionId
    >>> PreviousWindow(target=SessionId("$0")).render()
    ('previous-window', '-t', '$0')
    """

    kind = "previous_window"
    command = "previous-window"
    scope = "window"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects()

    alert: bool = False

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the optional ``-a`` flag."""
        return ("-a",) if self.alert else ()
