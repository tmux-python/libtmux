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
from libtmux.experimental.ops import (
    ClearHistory,
    FoldingPlanner,
    KillPane,
    LazyPlan,
    ListPanes,
    PaneId,
    ResizePane,
    RespawnPane,
    SelectPane,
    SendKeys,
    run,
)

if t.TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from libtmux.experimental.models.snapshots import PaneSnapshot
    from libtmux.experimental.ops import Planner, PlanResult
    from libtmux.experimental.ops._types import SlotRef

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

    def commands(self, mapper: Callable[[PaneRef], t.Any]) -> CommandPlan:
        """Build commands for each matched pane (folds to one dispatch on run).

        *mapper* receives a :class:`PaneRef` per matched pane and records
        operations through ``ref.cmd`` (e.g. ``ref.cmd.send_keys("clear")``); the
        returned :class:`CommandPlan` is pure until :meth:`CommandPlan.run`.
        """
        return CommandPlan(self, mapper)


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


@dataclass(frozen=True)
class BoundPaneCommands:
    """Pane commands bound to a target, recording into a shared plan.

    Each method appends a typed operation targeting the bound pane to the plan
    and returns its :class:`~..ops._types.SlotRef`, so commands compose and the
    plan folds to a single tmux dispatch.
    """

    plan: LazyPlan
    target: PaneId

    def send_keys(
        self,
        keys: str,
        *,
        enter: bool = True,
        suppress_history: bool = False,
    ) -> SlotRef:
        """Send *keys* to the pane (submitted with Enter unless ``enter=False``)."""
        return self.plan.add(
            SendKeys(
                target=self.target,
                keys=keys,
                enter=enter,
                suppress_history=suppress_history,
            ),
        )

    def resize(self, *, height: int | None = None, width: int | None = None) -> SlotRef:
        """Resize the pane to *height* rows and/or *width* columns."""
        return self.plan.add(
            ResizePane(target=self.target, height=height, width=width),
        )

    def select(self, *, zoom: bool = False) -> SlotRef:
        """Make the pane active (optionally zooming it)."""
        return self.plan.add(SelectPane(target=self.target, zoom=zoom))

    def respawn(self, *, kill: bool = False, shell: str | None = None) -> SlotRef:
        """Respawn the pane's command (``kill=True`` replaces a live one)."""
        return self.plan.add(
            RespawnPane(target=self.target, kill=kill, shell=shell),
        )

    def clear_history(self) -> SlotRef:
        """Clear the pane's scrollback history."""
        return self.plan.add(ClearHistory(target=self.target))

    def kill(self) -> SlotRef:
        """Kill the pane."""
        return self.plan.add(KillPane(target=self.target))


@dataclass(frozen=True)
class PaneRef:
    """A matched pane plus a ``cmd`` namespace that records into a plan."""

    pane: PaneSnapshot
    plan: LazyPlan

    @property
    def pane_id(self) -> str:
        """The pane's id."""
        return self.pane.pane_id

    @property
    def active(self) -> bool:
        """Whether the pane is active in its window."""
        return self.pane.active

    @property
    def cmd(self) -> BoundPaneCommands:
        """Pane commands bound to this pane (recorded into the plan)."""
        return BoundPaneCommands(self.plan, PaneId(self.pane.pane_id))


@dataclass(frozen=True)
class CommandPlan:
    """A pending bulk-command build: a query plus a per-pane command mapper.

    Pure until resolved -- :meth:`to_plan` records the operations against a source
    snapshot; :meth:`run` reads the source, builds, and dispatches (folding to a
    single tmux call by default).
    """

    query: PaneQuery
    mapper: Callable[[PaneRef], t.Any]

    def to_plan(self, source: PaneSource) -> LazyPlan:
        """Resolve the matched panes and record each one's commands into a plan.

        Examples
        --------
        >>> from libtmux.experimental.models.snapshots import PaneSnapshot
        >>> rows = [PaneSnapshot.from_format({"pane_id": "%1", "pane_active": "1"})]
        >>> cp = panes().filter(active=True).commands(
        ...     lambda p: p.cmd.send_keys("clear")
        ... )
        >>> plan = cp.to_plan(rows)
        >>> [op.kind for op in plan.operations]
        ['send_keys']
        >>> plan.operations[0].render()
        ('send-keys', '-t', '%1', 'clear', 'Enter')
        """
        plan = LazyPlan()
        for pane in self.query.all(source):
            self.mapper(PaneRef(pane, plan))
        return plan

    def run(
        self,
        engine: TmuxEngine,
        *,
        version: str | None = None,
        planner: Planner | None = None,
    ) -> PlanResult:
        """Read panes from *engine*, build the plan, and dispatch it.

        Folds the per-pane commands into a single tmux dispatch by default; pass
        *planner* to override.
        """
        plan = self.to_plan(engine)
        return plan.execute(
            engine, version=version, planner=planner or FoldingPlanner()
        )


def panes() -> PaneQuery:
    """Start a query over live panes.

    Examples
    --------
    >>> panes().filter(active=True).order_by("pane_index").limit(1)
    PaneQuery(lookups={'active': True}, order='pane_index', limit_count=1)
    """
    return PaneQuery()
