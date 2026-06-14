r"""Asyncio facade over the deferred query-command plan.

This is a thin wrapper over the sync
:mod:`~libtmux._experimental.chain.plan` engine: command
*construction* stays synchronous, and only snapshot resolution and command
dispatch become awaitable. A plan still compiles to exactly one
:class:`~libtmux._experimental.chain.ir.CommandChain`, so the
"one plan = one native ``\\;`` dispatch" guarantee is preserved -- it just runs
without blocking the event loop, and independent plans can resolve and dispatch
concurrently.

Note
----
This is an **experimental** API, not covered by the project's versioning policy.
It may change or be removed between any releases without notice.
"""

from __future__ import annotations

import dataclasses
import typing as t
from dataclasses import dataclass

from libtmux._experimental.chain import plan as sync_plan
from libtmux._experimental.chain.ir import (
    Arg,
    CommandChain,
    CommandResultLike,
)

MappedT = t.TypeVar("MappedT")
ResultT = t.TypeVar("ResultT")

NoCommandsResolved = sync_plan.NoCommandsResolved


class AsyncCommandRunner(t.Protocol):
    """Object capable of asynchronously dispatching one tmux command argv."""

    async def cmd(
        self,
        cmd: str,
        *args: Arg,
        target: str | int | None = None,
    ) -> CommandResultLike:
        """Dispatch one tmux command asynchronously."""
        ...


class AsyncSnapshotProvider(t.Protocol):
    """Object that can asynchronously provide a pure tmux snapshot."""

    async def snapshot(self) -> sync_plan.TmuxSnapshot:
        """Return a tmux snapshot asynchronously."""
        ...


class AsyncPlanRunner(AsyncCommandRunner, AsyncSnapshotProvider, t.Protocol):
    """A runner that can asynchronously resolve snapshots and dispatch."""


AsyncSnapshotSource: t.TypeAlias = "sync_plan.TmuxSnapshot | AsyncSnapshotProvider"


@dataclass(frozen=True, slots=True)
class PaneQuery:
    """An async lazy pane query backed by the sync query object.

    Construction stays synchronous; only :meth:`all`/:meth:`first` await a
    snapshot source.

    Examples
    --------
    >>> import asyncio
    >>> from libtmux._experimental.chain.plan import (
    ...     PaneRef, PaneTarget, SessionTarget, TmuxSnapshot, WindowTarget,
    ... )
    >>> snapshot = TmuxSnapshot(panes=(
    ...     PaneRef(PaneTarget("%1"), WindowTarget("@1"), SessionTarget("$0"),
    ...             pane_index=0, active=True, title="editor"),
    ... ))
    >>> rows = asyncio.run(panes().filter(active=True).all(snapshot))
    >>> [row.pane_id.value for row in rows]
    ['%1']
    """

    query: sync_plan.PaneQuery

    def filter(self, *, active: bool) -> PaneQuery:
        """Return a query filtered by active state."""
        return dataclasses.replace(self, query=self.query.filter(active=active))

    def order_by(self, field: sync_plan.OrderField) -> PaneQuery:
        """Return a query ordered by a known pane field."""
        return dataclasses.replace(self, query=self.query.order_by(field))

    def limit(self, count: int) -> PaneQuery:
        """Return a query capped to ``count`` rows."""
        return dataclasses.replace(self, query=self.query.limit(count))

    async def all(self, source: AsyncSnapshotSource) -> list[sync_plan.PaneRef]:
        """Evaluate the query against an async snapshot source."""
        snapshot = await _resolve_snapshot(source)
        return self.query.all(snapshot)

    async def first(self, source: AsyncSnapshotSource) -> sync_plan.PaneRef | None:
        """Evaluate the query and return its first row, or ``None``."""
        snapshot = await _resolve_snapshot(source)
        return self.query.first(snapshot)

    def map(
        self,
        mapper: t.Callable[[sync_plan.PaneRef], MappedT],
    ) -> MappedPaneQuery[MappedT]:
        """Return a data-only transformation query (no commands)."""
        return MappedPaneQuery(query=self, mapper=mapper)

    def commands(self, mapper: sync_plan.CommandMapper) -> CommandPlan[None]:
        """Return a deferred async multi-command side-effect plan."""
        return CommandPlan(query=self, mapper=mapper)


@dataclass(frozen=True, slots=True)
class MappedPaneQuery(t.Generic[MappedT]):
    """An async data-only query transformation over pane rows."""

    query: PaneQuery
    mapper: t.Callable[[sync_plan.PaneRef], MappedT]

    async def all(self, source: AsyncSnapshotSource) -> list[MappedT]:
        """Evaluate the query and transform every row."""
        return [self.mapper(row) for row in await self.query.all(source)]

    async def first(self, source: AsyncSnapshotSource) -> MappedT | None:
        """Evaluate the query and transform the first row, or ``None``."""
        row = await self.query.first(source)
        if row is None:
            return None
        return self.mapper(row)


@dataclass(frozen=True, slots=True)
class CommandPlan(t.Generic[ResultT]):
    """An async command plan that resolves a query into a command sequence.

    Examples
    --------
    >>> import asyncio
    >>> from libtmux._experimental.chain.plan import (
    ...     PaneRef, PaneTarget, SessionTarget, TmuxSnapshot, WindowTarget,
    ... )
    >>> snapshot = TmuxSnapshot(panes=(
    ...     PaneRef(PaneTarget("%2"), WindowTarget("@1"), SessionTarget("$0"),
    ...             pane_index=1, active=True, title="logs"),
    ...     PaneRef(PaneTarget("%1"), WindowTarget("@1"), SessionTarget("$0"),
    ...             pane_index=0, active=True, title="editor"),
    ... ))
    >>> async def _demo():
    ...     plan = (
    ...         panes()
    ...         .filter(active=True)
    ...         .order_by("pane_index")
    ...         .commands(lambda pane: pane.cmd.resize_pane(height=20))
    ...     )
    ...     sequence = await plan.to_chain(snapshot)
    ...     return sequence.argvs()
    >>> asyncio.run(_demo())
    (('resize-pane', '-t', '%1', '-y', '20'), ('resize-pane', '-t', '%2', '-y', '20'))
    """

    query: PaneQuery
    mapper: sync_plan.CommandMapper

    async def to_chain(self, source: AsyncSnapshotSource) -> CommandChain:
        """Resolve the async query and compile mapped commands.

        Reuses the sync compile path, so a plan still produces exactly one
        :class:`~libtmux._experimental.chain.ir.CommandChain`.
        """
        snapshot = await _resolve_snapshot(source)
        return self.query.query.commands(self.mapper).to_chain(snapshot)

    async def run(self: CommandPlan[None], runner: AsyncPlanRunner) -> None:
        """Resolve, compile, and dispatch the plan in one async invocation.

        An empty plan is a no-op (it does not raise).
        """
        try:
            sequence = await self.to_chain(runner)
        except NoCommandsResolved:
            return None
        argv = sequence.argv()
        await runner.cmd(argv[0], *argv[1:])
        return None


def panes() -> PaneQuery:
    """Start an async lazy pane query.

    Examples
    --------
    >>> panes().query
    PaneQuery(active_filter=None, ordering=None, limit_count=None)
    """
    return PaneQuery(sync_plan.panes())


async def _resolve_snapshot(source: AsyncSnapshotSource) -> sync_plan.TmuxSnapshot:
    if isinstance(source, sync_plan.TmuxSnapshot):
        return source
    return await source.snapshot()
