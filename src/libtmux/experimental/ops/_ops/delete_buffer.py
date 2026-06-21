"""The ``delete-buffer`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class DeleteBuffer(Operation[AckResult]):
    """Delete a paste buffer (``delete-buffer``).

    Parameters
    ----------
    buffer_name : str or None
        The buffer to delete (``-b``); the most recent when omitted.

    Examples
    --------
    >>> DeleteBuffer(buffer_name="b0").render()
    ('delete-buffer', '-b', 'b0')
    >>> DeleteBuffer().render()
    ('delete-buffer',)
    """

    kind = "delete_buffer"
    command = "delete-buffer"
    scope = "server"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects()

    buffer_name: str | None = None

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the optional ``-b`` buffer name."""
        if self.buffer_name is not None:
            return ("-b", self.buffer_name)
        return ()
