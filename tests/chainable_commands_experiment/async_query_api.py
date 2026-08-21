"""Piccolo-style async query experiment."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AsyncPaneRow:
    """Small async pane row."""

    pane_id: str
    active: bool


@dataclass(frozen=True, slots=True)
class AsyncPaneRunner:
    """Async runner returning fixed pane rows."""

    rows: tuple[AsyncPaneRow, ...]

    async def list_panes(self) -> list[AsyncPaneRow]:
        """Return pane rows asynchronously."""
        return list(self.rows)


@dataclass(frozen=True, slots=True)
class AsyncPaneQuery:
    """Immutable async pane query."""

    active_filter: bool | None = None
    limit_count: int | None = None

    def where(self, *, active: bool) -> AsyncPaneQuery:
        """Return a query filtered by active state."""
        return dataclasses.replace(self, active_filter=active)

    def limit(self, count: int) -> AsyncPaneQuery:
        """Return a query capped to ``count`` rows."""
        return dataclasses.replace(self, limit_count=count)

    async def all(self, runner: AsyncPaneRunner) -> list[AsyncPaneRow]:
        """Evaluate the async query."""
        rows = await runner.list_panes()
        if self.active_filter is not None:
            rows = [row for row in rows if row.active is self.active_filter]
        if self.limit_count is not None:
            rows = rows[: self.limit_count]
        return rows

    async def first(self, runner: AsyncPaneRunner) -> AsyncPaneRow | None:
        """Return the first matching row asynchronously."""
        rows = await self.limit(1).all(runner)
        if not rows:
            return None
        return rows[0]
