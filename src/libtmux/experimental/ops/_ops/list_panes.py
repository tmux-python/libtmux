"""The ``list-panes`` operation -- a typed read returning snapshots."""

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
from libtmux.experimental.ops.results import ListPanesResult

if t.TYPE_CHECKING:
    from libtmux.experimental.ops._types import Status


@register
@dataclass(frozen=True, kw_only=True)
class ListPanes(Operation[ListPanesResult]):
    """List panes and return typed snapshots (a read operation).

    Renders the same ``-F`` template the ORM reader uses (via
    :func:`libtmux.neo.get_output_format`) and parses each row into a
    :class:`~libtmux.experimental.models.PaneSnapshot`; with ``all_panes`` the
    result also exposes the full :class:`ServerSnapshot` tree.

    Parameters
    ----------
    all_panes : bool
        List panes across the whole server (``-a``).

    Examples
    --------
    >>> from libtmux.experimental.engines import MockEngine
    >>> from libtmux.experimental.ops import run
    >>> op = ListPanes()
    >>> op.render(version="3.6a")[:1]
    ('list-panes',)
    >>> "-a" in op.render(version="3.6a")
    True
    >>> result = run(op, MockEngine(), version="3.6a")
    >>> result.rows
    ()
    >>> result.server.sessions
    ()
    """

    kind = "list_panes"
    command = "list-panes"
    scope = "server"
    result_cls = ListPanesResult
    safety = "readonly"
    chainable = False
    effects = Effects(read_only=True, idempotent=True)

    all_panes: bool = True

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render ``-a`` (optional) and the ``-F`` format template."""
        _fields, fmt = get_output_format("list-panes", version or DEFAULT_LIST_VERSION)
        out: list[str] = []
        if self.all_panes:
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
    ) -> ListPanesResult:
        """Parse each output row into a pane format mapping."""
        ver = version or DEFAULT_LIST_VERSION
        rows = tuple(parse_output(line, "list-panes", ver) for line in stdout if line)
        return ListPanesResult(
            operation=self,
            argv=argv,
            status=status,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            rows=rows,
        )
