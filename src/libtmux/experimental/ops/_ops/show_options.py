"""The ``show-options`` operation -- typed option pairs."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import ShowOptionsResult

if t.TYPE_CHECKING:
    from libtmux.experimental.ops._types import Status


@register
@dataclass(frozen=True, kw_only=True)
class ShowOptions(Operation[ShowOptionsResult]):
    """Show options as ``name value`` pairs (``show-options``).

    Parameters
    ----------
    global_, server, window : bool
        Scope flags (``-g`` / ``-s`` / ``-w``).
    include_inherited : bool
        Include inherited options (``-A``).

    Examples
    --------
    >>> ShowOptions(global_=True).render()
    ('show-options', '-g')
    >>> ShowOptions().build_result(
    ...     returncode=0, stdout=("status on", "history-limit 2000")
    ... ).options["history-limit"]
    '2000'
    """

    kind = "show_options"
    command = "show-options"
    scope = "session"
    result_cls = ShowOptionsResult
    safety = "readonly"
    chainable = False
    effects = Effects(read_only=True, idempotent=True)

    global_: bool = False
    server: bool = False
    window: bool = False
    include_inherited: bool = False

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the scope/inheritance flags."""
        out: list[str] = []
        if self.global_:
            out.append("-g")
        if self.server:
            out.append("-s")
        if self.window:
            out.append("-w")
        if self.include_inherited:
            out.append("-A")
        return tuple(out)

    def _make_result(
        self,
        argv: tuple[str, ...],
        status: Status,
        returncode: int,
        stdout: tuple[str, ...],
        stderr: tuple[str, ...],
        version: str | None = None,
    ) -> ShowOptionsResult:
        """Parse ``name value`` lines into a mapping."""
        options: dict[str, str] = {}
        for line in stdout:
            name, _, value = line.partition(" ")
            options[name] = value
        return ShowOptionsResult(
            operation=self,
            argv=argv,
            status=status,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            options=options,
        )
