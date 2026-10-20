"""Polars-style lazy command plan experiment."""

from __future__ import annotations

import dataclasses
import typing as t
from dataclasses import dataclass

from .shared import CommandCall, CommandScope

SelectedField: t.TypeAlias = t.Literal["name", "target", "scope"]


@dataclass(frozen=True, slots=True)
class PlannedCall:
    """Command call with enough metadata for lazy filtering."""

    scope: CommandScope
    call: CommandCall


@dataclass(frozen=True, slots=True)
class CommandRow:
    """Collected command-row projection."""

    name: str
    target: str | int | None = None
    scope: CommandScope | None = None


@dataclass(frozen=True, slots=True)
class LazyCommandPlan:
    """Immutable lazy command-plan graph."""

    planned_calls: tuple[PlannedCall, ...]
    scope_filter: CommandScope | None = None
    selected_fields: tuple[SelectedField, ...] = ()

    @classmethod
    def from_calls(cls, calls: tuple[PlannedCall, ...]) -> LazyCommandPlan:
        """Create a lazy plan from planned calls."""
        return cls(calls)

    def filter_scope(self, scope: CommandScope) -> LazyCommandPlan:
        """Return a plan filtered by command scope."""
        return dataclasses.replace(self, scope_filter=scope)

    def select(self, *fields: SelectedField) -> LazyCommandPlan:
        """Return a plan with selected output fields."""
        return dataclasses.replace(self, selected_fields=fields)

    def optimize(self) -> LazyCommandPlan:
        """Return the optimized plan boundary."""
        return self

    def explain(self) -> tuple[str, ...]:
        """Render a tiny explanation of the lazy operations."""
        steps: list[str] = []
        if self.scope_filter is not None:
            steps.append(f"filter_scope={self.scope_filter}")
        if self.selected_fields:
            steps.append(f"select={','.join(self.selected_fields)}")
        return tuple(steps)

    def collect(self) -> list[CommandRow]:
        """Materialize the lazy plan into command rows."""
        rows: list[CommandRow] = []
        for planned_call in self.planned_calls:
            if (
                self.scope_filter is not None
                and planned_call.scope != self.scope_filter
            ):
                continue
            scope = planned_call.scope if "scope" in self.selected_fields else None
            rows.append(
                CommandRow(
                    name=planned_call.call.name,
                    target=planned_call.call.target,
                    scope=scope,
                ),
            )
        return rows
