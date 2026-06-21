"""The ``rename-window`` operation (no output -- an acknowledgement)."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class RenameWindow(Operation[AckResult]):
    """Rename a window. Produces no output; returns an :class:`AckResult`.

    Parameters
    ----------
    name : str
        The new window name.

    Examples
    --------
    >>> from libtmux.experimental.ops._types import WindowId
    >>> RenameWindow(target=WindowId("@1"), name="build").render()
    ('rename-window', '-t', '@1', 'build')
    """

    kind = "rename_window"
    command = "rename-window"
    scope = "window"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects(idempotent=True)

    name: str

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the new name."""
        return (self.name,)
