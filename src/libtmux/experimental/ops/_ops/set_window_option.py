"""The ``set-window-option`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class SetWindowOption(Operation[AckResult]):
    """Set a window option (``set-window-option``).

    Parameters
    ----------
    option : str
        The option name.
    value : str or None
        The value to set (omit when *unset* is true).
    global_ : bool
        Apply to all windows (``-g``).
    append : bool
        Append to a string/array option (``-a``).
    unset : bool
        Unset the option (``-u``).

    Examples
    --------
    >>> SetWindowOption(option="mode-keys", value="vi").render()
    ('set-window-option', 'mode-keys', 'vi')
    """

    kind = "set_window_option"
    command = "set-window-option"
    scope = "window"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects()

    option: str
    value: str | None = None
    global_: bool = False
    append: bool = False
    unset: bool = False

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the option flags, name, and value."""
        out: list[str] = []
        if self.append:
            out.append("-a")
        if self.global_:
            out.append("-g")
        if self.unset:
            out.append("-u")
        out.append(self.option)
        if self.value is not None and not self.unset:
            out.append(self.value)
        return tuple(out)
