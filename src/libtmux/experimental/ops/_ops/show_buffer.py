"""The ``show-buffer`` operation (a read returning buffer contents)."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import ShowBufferResult

if t.TYPE_CHECKING:
    from libtmux.experimental.ops._types import Status


@register
@dataclass(frozen=True, kw_only=True)
class ShowBuffer(Operation[ShowBufferResult]):
    r"""Show the contents of a paste buffer (``show-buffer``).

    Parameters
    ----------
    buffer_name : str or None
        The buffer to show (``-b``); the most recent when omitted.

    Examples
    --------
    >>> ShowBuffer(buffer_name="b0").render()
    ('show-buffer', '-b', 'b0')
    >>> ShowBuffer().build_result(returncode=0, stdout=("line1", "line2")).text
    'line1\nline2'
    """

    kind = "show_buffer"
    command = "show-buffer"
    scope = "server"
    result_cls = ShowBufferResult
    safety = "readonly"
    chainable = False
    effects = Effects(read_only=True, idempotent=True)

    buffer_name: str | None = None

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the optional ``-b`` buffer name."""
        if self.buffer_name is not None:
            return ("-b", self.buffer_name)
        return ()

    def _make_result(
        self,
        argv: tuple[str, ...],
        status: Status,
        returncode: int,
        stdout: tuple[str, ...],
        stderr: tuple[str, ...],
        version: str | None = None,
    ) -> ShowBufferResult:
        """Join the captured lines into the buffer text."""
        return ShowBufferResult(
            operation=self,
            argv=argv,
            status=status,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            text="\n".join(stdout),
        )
