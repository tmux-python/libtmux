"""A lazy, snapshot-backed query over live tmux panes.

This is the live-object query layer (distinct from the declarative workspace IR):
``panes()`` builds an immutable query that resolves against a *snapshot* of the
live server -- either taken from an engine (a ``list-panes`` read) or supplied as
a pure sequence of :class:`~libtmux.experimental.models.snapshots.PaneSnapshot`.
Filtering reuses :class:`~libtmux._internal.query_list.QueryList`, so the same
Django-style lookups that power ``server.panes`` work here against snapshots.

The query is pure and chainable; nothing runs until a terminal method
(:meth:`PaneQuery.all` / :meth:`PaneQuery.first`) resolves it against a source.

Examples
--------
>>> from libtmux.experimental.models.snapshots import PaneSnapshot
>>> rows = [
...     PaneSnapshot.from_format({"pane_id": "%1", "pane_index": "0",
...                               "pane_active": "1", "pane_current_command": "vim"}),
...     PaneSnapshot.from_format({"pane_id": "%2", "pane_index": "1",
...                               "pane_active": "0", "pane_current_command": "zsh"}),
... ]
>>> panes().filter(active=True).map(lambda p: p.pane_id).all(rows)
('%1',)
>>> panes().order_by("pane_index").map(lambda p: p.pane_id).all(rows)
('%1', '%2')
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field, replace

from libtmux._internal.query_list import QueryList
from libtmux.experimental.engines.base import TmuxEngine
from libtmux.experimental.ops import ListPanes, run

if t.TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from libtmux.experimental.models.snapshots import PaneSnapshot

#: A source of pane snapshots: an engine to read from, or pre-taken snapshots.
PaneSource = t.Union["TmuxEngine", "Sequence[PaneSnapshot]"]
MappedT = t.TypeVar("MappedT")


def _snapshot_panes(source: PaneSource) -> tuple[PaneSnapshot, ...]:
    """Resolve *source* into pane snapshots (read an engine, or pass through)."""
    if isinstance(source, TmuxEngine):
        return run(ListPanes(), source).panes
    return tuple(source)


def _order_key(pane: PaneSnapshot, field_name: str) -> tuple[bool, t.Any]:
    """Sort key for ``order_by`` that sorts missing (``None``) values last."""
    value = getattr(pane, field_name, None)
    return (value is None, value)


@dataclass(frozen=True)
class PaneQuery:
    """An immutable, chainable query over pane snapshots.

    Each method returns a new query; :meth:`all` / :meth:`first` resolve it
    against a :data:`PaneSource`.
    """

    lookups: Mapping[str, t.Any] = field(default_factory=dict)
    order: str | None = None
    limit_count: int | None = None

    def filter(self, **lookups: t.Any) -> PaneQuery:
        """Narrow by QueryList lookups (e.g. ``active=True``, ``pane_index=0``)."""
        return replace(self, lookups={**self.lookups, **lookups})

    def order_by(self, field_name: str) -> PaneQuery:
        """Sort the results by a snapshot attribute (missing values last)."""
        return replace(self, order=field_name)

    def limit(self, count: int) -> PaneQuery:
        """Keep only the first *count* results."""
        return replace(self, limit_count=count)

    def all(self, source: PaneSource) -> tuple[PaneSnapshot, ...]:
        """Resolve the query against *source* and return the matched snapshots."""
        rows: t.Any = QueryList(_snapshot_panes(source))
        if self.lookups:
            rows = rows.filter(**self.lookups)
        rows = list(rows)
        if self.order is not None:
            rows.sort(key=lambda pane: _order_key(pane, self.order))
        if self.limit_count is not None:
            rows = rows[: self.limit_count]
        return tuple(rows)

    def first(self, source: PaneSource) -> PaneSnapshot | None:
        """Return the first matched snapshot, or ``None`` when none match."""
        rows = self.all(source)
        return rows[0] if rows else None

    def map(self, fn: Callable[[PaneSnapshot], MappedT]) -> MappedPaneQuery[MappedT]:
        """Project each matched snapshot through *fn* (a pure read projection)."""
        return MappedPaneQuery(self, fn)


@dataclass(frozen=True)
class MappedPaneQuery(t.Generic[MappedT]):
    """A :class:`PaneQuery` whose rows are projected through a function."""

    query: PaneQuery
    fn: Callable[[PaneSnapshot], MappedT]

    def all(self, source: PaneSource) -> tuple[MappedT, ...]:
        """Resolve and project every matched snapshot."""
        return tuple(self.fn(pane) for pane in self.query.all(source))

    def first(self, source: PaneSource) -> MappedT | None:
        """Resolve and project the first matched snapshot, or ``None``."""
        first = self.query.first(source)
        return self.fn(first) if first is not None else None


def panes() -> PaneQuery:
    """Start a query over live panes.

    Examples
    --------
    >>> panes().filter(active=True).order_by("pane_index").limit(1)
    PaneQuery(lookups={'active': True}, order='pane_index', limit_count=1)
    """
    return PaneQuery()
