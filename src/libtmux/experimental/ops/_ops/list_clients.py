"""The ``list-clients`` operation -- typed client snapshots."""

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
from libtmux.experimental.ops.results import ListClientsResult

if t.TYPE_CHECKING:
    from libtmux.experimental.ops._types import Status


@register
@dataclass(frozen=True, kw_only=True)
class ListClients(Operation[ListClientsResult]):
    """List attached clients and return typed snapshots.

    Examples
    --------
    >>> from libtmux.experimental.engines import ConcreteEngine
    >>> from libtmux.experimental.ops import run
    >>> run(ListClients(), ConcreteEngine(), version="3.6a").clients
    ()
    """

    kind = "list_clients"
    command = "list-clients"
    scope = "server"
    result_cls = ListClientsResult
    safety = "readonly"
    chainable = False
    effects = Effects(read_only=True, idempotent=True)

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the ``-F`` format template."""
        _fields, fmt = get_output_format(
            "list-clients", version or DEFAULT_LIST_VERSION
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
    ) -> ListClientsResult:
        """Parse each output row into a client format mapping."""
        ver = version or DEFAULT_LIST_VERSION
        rows = tuple(parse_output(line, "list-clients", ver) for line in stdout if line)
        return ListClientsResult(
            operation=self,
            argv=argv,
            status=status,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            rows=rows,
        )
