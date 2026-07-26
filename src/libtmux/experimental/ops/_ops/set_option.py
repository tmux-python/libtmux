"""The ``set-option`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation, positional_args
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class SetOption(Operation[AckResult]):
    """Set a tmux option (``set-option``); the write counterpart to show-options.

    Attributes
    ----------
    option : str
        The option name.
    value : str or None
        The value to set (omit when *unset* is true).
    global_ : bool
        Set a global option (``-g``).
    server : bool
        Set a server option (``-s``).
    window : bool
        Set a window option (``-w``).
    pane : bool
        Set a pane option (``-p``).
    append : bool
        Append to a string/array option (``-a``).
    unset : bool
        Unset the option (``-u``).
    quiet : bool
        Suppress errors (``-q``).

    Examples
    --------
    >>> SetOption(option="status", value="on").render()
    ('set-option', '--', 'status', 'on')
    >>> SetOption(global_=True, option="status", value="on").render()
    ('set-option', '-g', '--', 'status', 'on')
    >>> SetOption(option="status", unset=True).render()
    ('set-option', '-u', '--', 'status')
    """

    kind = "set_option"
    command = "set-option"
    scope = "session"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects()

    option: str
    value: str | None = None
    global_: bool = False
    server: bool = False
    window: bool = False
    pane: bool = False
    append: bool = False
    unset: bool = False
    quiet: bool = False

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the option flags, name, and value."""
        out: list[str] = []
        if self.append:
            out.append("-a")
        if self.global_:
            out.append("-g")
        if self.server:
            out.append("-s")
        if self.window:
            out.append("-w")
        if self.pane:
            out.append("-p")
        if self.quiet:
            out.append("-q")
        if self.unset:
            out.append("-u")
        positional = [self.option]
        if self.value is not None and not self.unset:
            positional.append(self.value)
        out.extend(positional_args(*positional))
        return tuple(out)
