"""The ``display-message -p`` operation -- a typed format query."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import DisplayMessageResult

if t.TYPE_CHECKING:
    from libtmux.experimental.ops._types import Status


@register
@dataclass(frozen=True, kw_only=True)
class DisplayMessage(Operation[DisplayMessageResult]):
    """Evaluate a tmux format and print it (``display-message -p``).

    Examples
    --------
    >>> from libtmux.experimental.ops._types import PaneId
    >>> DisplayMessage(target=PaneId("%1"), message="#{pane_width}").render()
    ('display-message', '-t', '%1', '-p', '#{pane_width}')
    >>> DisplayMessage(message="#{pane_id}").build_result(
    ...     returncode=0, stdout=("%1",)
    ... ).text
    '%1'
    """

    kind = "display_message"
    command = "display-message"
    scope = "pane"
    result_cls = DisplayMessageResult
    safety = "readonly"
    chainable = False
    effects = Effects(read_only=True, reads_output=True, idempotent=True)

    message: str

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render ``-p <format>``."""
        return ("-p", self.message)

    def _make_result(
        self,
        argv: tuple[str, ...],
        status: Status,
        returncode: int,
        stdout: tuple[str, ...],
        stderr: tuple[str, ...],
        version: str | None = None,
    ) -> DisplayMessageResult:
        """Expose the printed line as :attr:`~.DisplayMessageResult.text`."""
        return DisplayMessageResult(
            operation=self,
            argv=argv,
            status=status,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            text=stdout[0] if stdout else "",
        )
