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
        Append an ``Enter`` key after the input. Cannot be combined with
        *literal* -- under ``-l`` tmux would type the text "Enter" rather than
        pressing Return; send the keys and Enter as two operations instead.
    literal : bool
        Send keys literally without tmux key-name lookup (``-l``).
    suppress_history : bool
        Prepend a single space to the command so an ``ignorespace``-configured
        shell (``HISTCONTROL=ignorespace``) keeps it out of history -- the same
        trick tmuxp uses. No-op when *literal* is set.

    Examples
    --------
    >>> from libtmux.experimental.ops._types import PaneId
    >>> SendKeys(target=PaneId("%1"), keys="echo hi", enter=True).render()
    ('send-keys', '-t', '%1', 'echo hi', 'Enter')
    >>> SendKeys(target=PaneId("%1"), keys="q", literal=True).render()
    ('send-keys', '-t', '%1', '-l', 'q')
    >>> SendKeys(target=PaneId("%1"), keys="vim", suppress_history=True).render()
    ('send-keys', '-t', '%1', ' vim')
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
    suppress_history: bool = False

    def __post_init__(self) -> None:
        """Reject literal+enter (fail closed): tmux ``-l`` types "Enter"."""
        if self.literal and self.enter:
            msg = (
                "send-keys cannot combine literal=True with enter=True; under -l "
                "tmux types the text 'Enter' -- send the keys and Enter separately"
            )
            raise ValueError(msg)

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render ``send-keys`` flags and the key string."""
        out: list[str] = []
        if self.literal:
            out.append("-l")
        keys = self.keys
        if self.suppress_history and not self.literal:
            keys = f" {keys}"
        out.append(keys)
        if self.enter:
            out.append("Enter")
        return tuple(out)
