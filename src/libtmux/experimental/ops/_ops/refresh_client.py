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

    Parameters
    ----------
    subscribe : str, optional
        Format spec passed to ``-B``; subscribes the control client to a
        named format notification.
    size : str, optional
        Geometry passed to ``-C`` (e.g. ``"200x50"``); overrides the
        client's reported size.

    Examples
    --------
    >>> from libtmux.experimental.ops._types import ClientName
    >>> RefreshClient(target=ClientName("/dev/pts/3")).render()
    ('refresh-client', '-t', '/dev/pts/3')
    >>> op = RefreshClient(
    ...     target=ClientName("/dev/pts/3"),
    ...     subscribe="agentstate:%*:#{@agent_state}",
    ... )
    >>> op.render()
    ('refresh-client', '-t', '/dev/pts/3', '-B', 'agentstate:%*:#{@agent_state}')
    """

    kind = "refresh_client"
    command = "refresh-client"
    scope = "client"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects(idempotent=True)

    subscribe: str | None = None
    size: str | None = None

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Emit ``-B <spec>`` and/or ``-C <size>`` when set.

        Examples
        --------
        >>> from libtmux.experimental.ops._types import ClientName
        >>> RefreshClient(target=ClientName("/dev/pts/3"), size="200x50").args()
        ('-C', '200x50')
        """
        out: list[str] = []
        if self.subscribe is not None:
            out += ["-B", self.subscribe]
        if self.size is not None:
            out += ["-C", self.size]
        return tuple(out)
