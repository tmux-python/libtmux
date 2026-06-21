"""The ``send-keys`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class SendKeys(Operation[AckResult]):
    """Send keys (input) to a pane.

    Parameters
    ----------
    keys : str
        The key string to send.
    enter : bool
        Append a literal ``Enter`` key after the input.
    literal : bool
        Send keys literally without tmux key-name lookup (``-l``).

    Examples
    --------
    >>> from libtmux.experimental.ops._types import PaneId
    >>> SendKeys(target=PaneId("%1"), keys="echo hi", enter=True).render()
    ('send-keys', '-t', '%1', 'echo hi', 'Enter')
    >>> SendKeys(target=PaneId("%1"), keys="q", literal=True).render()
    ('send-keys', '-t', '%1', '-l', 'q')
    """

    kind = "send_keys"
    command = "send-keys"
    scope = "pane"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects(writes_input=True)

    keys: str
    enter: bool = False
    literal: bool = False

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render ``send-keys`` flags and the key string."""
        out: list[str] = []
        if self.literal:
            out.append("-l")
        out.append(self.keys)
        if self.enter:
            out.append("Enter")
        return tuple(out)
