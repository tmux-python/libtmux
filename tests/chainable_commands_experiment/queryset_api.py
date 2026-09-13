"""Django QuerySet-style lazy query experiment."""

from __future__ import annotations

import dataclasses
import typing as t
from dataclasses import dataclass

OrderField: t.TypeAlias = t.Literal["pane_id", "pane_index", "title"]


@dataclass(frozen=True, slots=True)
class PaneRow:
    """Small pane row returned by the query demo."""

    pane_id: str
    pane_index: int
    active: bool
    title: str


@dataclass(frozen=True, slots=True)
class StaticPaneRunner:
    """Runner exposing fixed pane rows."""

    rows: tuple[PaneRow, ...]

    def list_panes(self) -> list[PaneRow]:
        """Return pane rows for query evaluation."""
        return list(self.rows)


@dataclass(frozen=True, slots=True)
class PaneQuery:
    """Lazy, immutable pane query."""

    active_filter: bool | None = None
    ordering: OrderField | None = None
    limit_count: int | None = None

    def filter(self, *, active: bool) -> PaneQuery:
        """Return a query filtered by active state."""
        return dataclasses.replace(self, active_filter=active)

    def order_by(self, field: OrderField) -> PaneQuery:
        """Return a query ordered by a known pane field."""
        return dataclasses.replace(self, ordering=field)

    def limit(self, count: int) -> PaneQuery:
        """Return a query capped to ``count`` rows."""
        return dataclasses.replace(self, limit_count=count)

    def all(self, runner: StaticPaneRunner) -> list[PaneRow]:
        """Evaluate the query and return all matching rows."""
        rows = runner.list_panes()
        if self.active_filter is not None:
            rows = [row for row in rows if row.active is self.active_filter]
        if self.ordering is not None:
            ordering = self.ordering
            rows.sort(key=lambda row: _order_value(row, ordering))
        if self.limit_count is not None:
            rows = rows[: self.limit_count]
        return rows

    def first(self, runner: StaticPaneRunner) -> PaneRow | None:
        """Evaluate the query and return its first row."""
        rows = self.limit(1).all(runner)
        if not rows:
            return None
        return rows[0]


def _order_value(row: PaneRow, field: OrderField) -> str | int:
    if field == "pane_id":
        return row.pane_id
    if field == "pane_index":
        return row.pane_index
    return row.title
