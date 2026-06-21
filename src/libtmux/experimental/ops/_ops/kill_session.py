"""The ``kill-session`` operation (no output -- an acknowledgement)."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class KillSession(Operation[AckResult]):
    """Kill a session. Destructive; produces no output (:class:`AckResult`).

    Examples
    --------
    >>> from libtmux.experimental.ops._types import SessionId
    >>> KillSession(target=SessionId("$0")).render()
    ('kill-session', '-t', '$0')
    """

    kind = "kill_session"
    command = "kill-session"
    scope = "session"
    result_cls = AckResult
    safety = "destructive"
    effects = Effects(destructive=True)

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """No positional arguments beyond the target."""
        return ()
