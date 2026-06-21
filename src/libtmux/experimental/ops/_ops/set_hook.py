"""The ``set-hook`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class SetHook(Operation[AckResult]):
    """Set or unset a tmux hook (``set-hook``).

    Parameters
    ----------
    name : str
        The hook name (e.g. ``after-new-window``).
    hook_command : str or None
        The tmux command to run (omit when *unset*).
    global_ : bool
        Apply globally (``-g``).
    unset : bool
        Unset the hook (``-u``).

    Examples
    --------
    >>> SetHook(name="after-new-window", hook_command="display hi").render()
    ('set-hook', 'after-new-window', 'display hi')
    """

    kind = "set_hook"
    command = "set-hook"
    scope = "session"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects()

    name: str
    hook_command: str | None = None
    global_: bool = False
    unset: bool = False

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the flags, hook name, and command."""
        out: list[str] = []
        if self.global_:
            out.append("-g")
        if self.unset:
            out.append("-u")
        out.append(self.name)
        if self.hook_command is not None and not self.unset:
            out.append(self.hook_command)
        return tuple(out)
