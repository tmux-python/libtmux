"""The ``switch-client`` operation (no output -- an acknowledgement)."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class SwitchClient(Operation[AckResult]):
    """Switch a client to a session. Produces no output (:class:`AckResult`).

    Uses ``-c`` for the client and ``-t`` for the destination session, so it
    does not use the generic target slot.

    Examples
    --------
    >>> SwitchClient(client="/dev/pts/3", to_session="$1").render()
    ('switch-client', '-c', '/dev/pts/3', '-t', '$1')
    """

    kind = "switch_client"
    command = "switch-client"
    scope = "client"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects()

    client: str
    to_session: str

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render ``-c <client> -t <session>``."""
        return ("-c", self.client, "-t", self.to_session)
