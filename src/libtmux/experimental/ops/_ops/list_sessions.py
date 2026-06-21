"""The ``list-sessions`` operation -- a typed read returning snapshots."""

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
from libtmux.experimental.ops.results import ListSessionsResult

if t.TYPE_CHECKING:
    from libtmux.experimental.ops._types import Status


@register
@dataclass(frozen=True, kw_only=True)
class ListSessions(Operation[ListSessionsResult]):
    """List the server's sessions and return typed :class:`SessionSnapshot` rows.

    Examples
    --------
    >>> from libtmux.experimental.engines import ConcreteEngine
    >>> from libtmux.experimental.ops import run
    >>> run(ListSessions(), ConcreteEngine(), version="3.6a").sessions
    ()
    """

    kind = "list_sessions"
    command = "list-sessions"
    scope = "server"
    result_cls = ListSessionsResult
    safety = "readonly"
    chainable = False
    effects = Effects(read_only=True, idempotent=True)

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the ``-F`` format template (list-sessions is server-wide)."""
        _fields, fmt = get_output_format(
            "list-sessions",
            version or DEFAULT_LIST_VERSION,
        )
        return ("-F", fmt)

    def _make_result(
        self,
        argv: tuple[str, ...],
        status: Status,
        returncode: int,
        stdout: tuple[str, ...],
        stderr: tuple[str, ...],
        version: str | None = None,
    ) -> ListSessionsResult:
        """Parse each output row into a session format mapping."""
        ver = version or DEFAULT_LIST_VERSION
        rows = tuple(
            parse_output(line, "list-sessions", ver) for line in stdout if line
        )
        return ListSessionsResult(
            operation=self,
            argv=argv,
            status=status,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            rows=rows,
        )
