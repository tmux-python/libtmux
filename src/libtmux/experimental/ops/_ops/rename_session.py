"""The ``rename-session`` operation (no output -- an acknowledgement)."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class RenameSession(Operation[AckResult]):
    """Rename a session. Produces no output (:class:`AckResult`).

    Examples
    --------
    >>> from libtmux.experimental.ops._types import SessionId
    >>> RenameSession(target=SessionId("$0"), name="work").render()
    ('rename-session', '-t', '$0', 'work')
    """

    kind = "rename_session"
    command = "rename-session"
    scope = "session"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects(idempotent=True)

    name: str

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the new session name."""
        return (self.name,)
