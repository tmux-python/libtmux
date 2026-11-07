"""The ``last-window`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class LastWindow(Operation[AckResult]):
    """Select the previously active window (``last-window``).

    ``target`` is the session.

    Examples
    --------
    >>> from libtmux.experimental.ops._types import SessionId
    >>> LastWindow(target=SessionId("$0")).render()
    ('last-window', '-t', '$0')
    """

    kind = "last_window"
    command = "last-window"
    scope = "window"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects(idempotent=True)
