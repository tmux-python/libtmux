"""The ``kill-server`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class KillServer(Operation[AckResult]):
    """Kill the tmux server and all its sessions (``kill-server``).

    Examples
    --------
    >>> KillServer().render()
    ('kill-server',)
    """

    kind = "kill_server"
    command = "kill-server"
    scope = "server"
    result_cls = AckResult
    safety = "destructive"
    effects = Effects(destructive=True)
