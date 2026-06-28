"""The ``start-server`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class StartServer(Operation[AckResult]):
    """Start the tmux server if it is not already running (``start-server``).

    Examples
    --------
    >>> StartServer().render()
    ('start-server',)
    """

    kind = "start_server"
    command = "start-server"
    scope = "server"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects(idempotent=True)
