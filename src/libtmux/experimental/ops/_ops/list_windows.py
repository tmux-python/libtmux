"""The ``list-windows`` operation -- a typed read returning snapshots."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops._read import (
    DEFAULT_LIST_VERSION,
    get_output_format,
    parse_output,
)
from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import ListWindowsResult

if t.TYPE_CHECKING:
    from libtmux.experimental.ops._types import Status


@register
@dataclass(frozen=True, kw_only=True)
class ListWindows(Operation[ListWindowsResult]):
    """List windows and return typed :class:`WindowSnapshot` rows.

    Parameters
    ----------
    all_windows : bool
        List windows across the whole server (``-a``).

    Examples
    --------
    >>> from libtmux.experimental.engines import MockEngine
    >>> from libtmux.experimental.ops import run
    >>> run(ListWindows(), MockEngine(), version="3.6a").windows
    ()
    """

    kind = "list_windows"
    command = "list-windows"
    scope = "server"
    result_cls = ListWindowsResult
    safety = "readonly"
    chainable = False
    effects = Effects(read_only=True, idempotent=True)

    all_windows: bool = True

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render ``-a`` (optional) and the ``-F`` format template."""
        _fields, fmt = get_output_format(
            "list-windows", version or DEFAULT_LIST_VERSION
        )
        out: list[str] = []
        if self.all_windows:
            out.append("-a")
        out.extend(("-F", fmt))
        return tuple(out)

    def _make_result(
        self,
        argv: tuple[str, ...],
        status: Status,
        returncode: int,
        stdout: tuple[str, ...],
        stderr: tuple[str, ...],
        version: str | None = None,
    ) -> ListWindowsResult:
        """Parse each output row into a window format mapping."""
        ver = version or DEFAULT_LIST_VERSION
        rows = tuple(parse_output(line, "list-windows", ver) for line in stdout if line)
        return ListWindowsResult(
            operation=self,
            argv=argv,
            status=status,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            rows=rows,
        )
