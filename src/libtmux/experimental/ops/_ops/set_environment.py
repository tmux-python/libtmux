"""The ``set-environment`` operation."""

from __future__ import annotations

from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult


@register
@dataclass(frozen=True, kw_only=True)
class SetEnvironment(Operation[AckResult]):
    """Set or unset a session environment variable (``set-environment``).

    Parameters
    ----------
    name : str
        The variable name.
    value : str or None
        The value to set (omit when *remove*/*unset*).
    global_ : bool
        Apply to the global environment (``-g``).
    remove : bool
        Remove the variable from the environment (``-r``).
    unset : bool
        Unset the variable (``-u``).

    Examples
    --------
    >>> SetEnvironment(name="FOO", value="bar").render()
    ('set-environment', 'FOO', 'bar')
    >>> SetEnvironment(global_=True, name="FOO", unset=True).render()
    ('set-environment', '-g', '-u', 'FOO')
    """

    kind = "set_environment"
    command = "set-environment"
    scope = "session"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects()

    name: str
    value: str | None = None
    global_: bool = False
    remove: bool = False
    unset: bool = False

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the flags, name, and value."""
        out: list[str] = []
        if self.global_:
            out.append("-g")
        if self.remove:
            out.append("-r")
        if self.unset:
            out.append("-u")
        out.append(self.name)
        if self.value is not None and not (self.unset or self.remove):
            out.append(self.value)
        return tuple(out)
