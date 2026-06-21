"""The ``refresh-client`` operation (no output -- an acknowledgement)."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class RefreshClient(Operation[AckResult]):
    """Refresh a client. Produces no output (:class:`AckResult`).

    Examples
    --------
    >>> from libtmux.experimental.ops._types import ClientName
    >>> RefreshClient(target=ClientName("/dev/pts/3")).render()
    ('refresh-client', '-t', '/dev/pts/3')
    """

    kind = "refresh_client"
    command = "refresh-client"
    scope = "client"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects(idempotent=True)

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """No positional arguments beyond the target client."""
        return ()
