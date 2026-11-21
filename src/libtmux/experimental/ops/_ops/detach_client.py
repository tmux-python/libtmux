"""The ``detach-client`` operation (no output -- an acknowledgement)."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class DetachClient(Operation[AckResult]):
    """Detach a client. Produces no output (:class:`AckResult`).

    ``target`` is the client (a :class:`~.._types.ClientName`).

    Examples
    --------
    >>> from libtmux.experimental.ops._types import ClientName
    >>> DetachClient(target=ClientName("/dev/pts/3")).render()
    ('detach-client', '-t', '/dev/pts/3')
    """

    kind = "detach_client"
    command = "detach-client"
    scope = "client"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects()

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """No positional arguments beyond the target client."""
        return ()
