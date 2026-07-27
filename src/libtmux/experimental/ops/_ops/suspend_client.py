"""The ``suspend-client`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class SuspendClient(Operation[AckResult]):
    """Suspend a client (``suspend-client``).

    ``target`` is the client to suspend.

    Examples
    --------
    >>> from libtmux.experimental.ops._types import ClientName
    >>> SuspendClient(target=ClientName("/dev/pts/1")).render()
    ('suspend-client', '-t', '/dev/pts/1')
    """

    kind = "suspend_client"
    command = "suspend-client"
    scope = "client"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects()
