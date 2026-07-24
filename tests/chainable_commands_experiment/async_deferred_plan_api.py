"""Asyncio facade over deferred query-command plan experiments."""

from __future__ import annotations

import dataclasses
import typing as t
from dataclasses import dataclass

from . import deferred_plan_api as sync_api
from .shared import Arg, CommandCall, CommandResultLike

MappedT = t.TypeVar("MappedT")
ResultT = t.TypeVar("ResultT")

NoCommandsResolved = sync_api.NoCommandsResolved


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

    async def snapshot(self) -> sync_api.TmuxSnapshot:
        """Return a tmux snapshot asynchronously."""
        ...


class AsyncPlanRunner(
    AsyncCommandRunner,
    AsyncSnapshotProvider,
    t.Protocol,
):
    """Runner that can resolve async queries and dispatch async commands."""


AsyncSnapshotSource: t.TypeAlias = sync_api.TmuxSnapshot | AsyncSnapshotProvider


@dataclass(frozen=True, slots=True)
class PaneQuery:
    """Async lazy pane query backed by the sync deferred query object."""

    query: sync_api.PaneQuery

    def filter(self, *, active: bool) -> PaneQuery:
        """Return a query filtered by active state."""
        return dataclasses.replace(self, query=self.query.filter(active=active))

    def order_by(self, field: sync_api.OrderField) -> PaneQuery:
        """Return a query ordered by a known pane field."""
        return dataclasses.replace(self, query=self.query.order_by(field))

    def limit(self, count: int) -> PaneQuery:
        """Return a query capped to ``count`` rows."""
        return dataclasses.replace(self, query=self.query.limit(count))

    async def all(self, source: AsyncSnapshotSource) -> list[sync_api.PaneRef]:
        """Evaluate the query against an async snapshot source."""
        snapshot = await _resolve_snapshot(source)
        return self.query.all(snapshot)

    async def first(
        self,
        source: AsyncSnapshotSource,
    ) -> sync_api.PaneRef | None:
        """Evaluate the query and return its first row."""
        snapshot = await _resolve_snapshot(source)
        return self.query.first(snapshot)

    def map(
        self,
        mapper: t.Callable[[sync_api.PaneRef], MappedT],
    ) -> MappedPaneQuery[MappedT]:
        """Return a data transformation query."""
        return MappedPaneQuery(query=self, mapper=mapper)

    def each(self, mapper: sync_api.CommandMapper) -> CommandPlan[None]:
        """Return a deferred async side-effect command plan."""
        return self.flat_map(mapper)

    def flat_map(self, mapper: sync_api.CommandMapper) -> CommandPlan[None]:
        """Return a deferred async multi-command side-effect plan."""
        return CommandPlan(query=self, mapper=mapper)


@dataclass(frozen=True, slots=True)
class MappedPaneQuery(t.Generic[MappedT]):
    """Async data-only query transformation over pane refs."""

    query: PaneQuery
    mapper: t.Callable[[sync_api.PaneRef], MappedT]

    async def all(self, source: AsyncSnapshotSource) -> list[MappedT]:
        """Evaluate the query and transform every row."""
        return [self.mapper(row) for row in await self.query.all(source)]

    async def first(self, source: AsyncSnapshotSource) -> MappedT | None:
        """Evaluate the query and transform the first row."""
        row = await self.query.first(source)
        if row is None:
            return None
        return self.mapper(row)


@dataclass(frozen=True, slots=True)
class CommandSequence:
    """Async wrapper around a resolved sync command sequence."""

    sequence: sync_api.CommandSequence

    @property
    def calls(self) -> tuple[CommandCall, ...]:
        """Return resolved command calls."""
        return self.sequence.calls

    def argvs(self) -> tuple[tuple[str, ...], ...]:
        """Render each command independently."""
        return self.sequence.argvs()

    def argv(self) -> tuple[str, ...]:
        """Render one native tmux semicolon command sequence."""
        return self.sequence.argv()

    async def run(self, runner: AsyncCommandRunner) -> CommandResultLike:
        """Dispatch the sequence through one async runner call."""
        argv = self.argv()
        return await runner.cmd(argv[0], *argv[1:])


@dataclass(frozen=True, slots=True)
class CommandPlan(t.Generic[ResultT]):
    """Async command plan that resolves a query into commands."""

    query: PaneQuery
    mapper: sync_api.CommandMapper

    async def to_sequence(self, source: AsyncSnapshotSource) -> CommandSequence:
        """Resolve the async query and compile mapped commands."""
        snapshot = await _resolve_snapshot(source)
        plan = self.query.query.flat_map(self.mapper)
        return CommandSequence(plan.to_sequence(snapshot))

    async def run(self: CommandPlan[None], runner: AsyncPlanRunner) -> None:
        """Resolve, compile, and execute the plan through one async dispatch."""
        try:
            sequence = await self.to_sequence(runner)
        except NoCommandsResolved:
            return None
        await sequence.run(runner)
        return None


def panes() -> PaneQuery:
    """Start an async lazy pane query."""
    return PaneQuery(sync_api.panes())


async def _resolve_snapshot(source: AsyncSnapshotSource) -> sync_api.TmuxSnapshot:
    if isinstance(source, sync_api.TmuxSnapshot):
        return source
    return await source.snapshot()
