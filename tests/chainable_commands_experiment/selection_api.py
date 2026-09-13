"""GraphQL-style nested selection experiment."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

ScopeName = str
FieldName = str
SelectionPayload = dict[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class SelectionPlan:
    """Compiled nested selection plan."""

    scopes: tuple[ScopeName, ...]
    fields: tuple[FieldName, ...]


@dataclass(frozen=True, slots=True)
class SelectionQuery:
    """Immutable nested tmux selection query."""

    scopes: tuple[ScopeName, ...]
    selected_fields: tuple[FieldName, ...] = ()

    def sessions(self) -> SelectionQuery:
        """Select session depth."""
        return self._include("session")

    def windows(self) -> SelectionQuery:
        """Select window depth."""
        return self._include("window")

    def panes(self) -> SelectionQuery:
        """Select pane depth."""
        return self._include("pane")

    def fields(self, *field_names: FieldName) -> SelectionQuery:
        """Select fields at the current depth."""
        return dataclasses.replace(self, selected_fields=field_names)

    def compile(self) -> SelectionPlan:
        """Compile the nested selection."""
        return SelectionPlan(self.scopes, self.selected_fields)

    def run(self, runner: StaticSelectionRunner) -> SelectionPayload:
        """Execute the nested selection through a runner."""
        return runner.run(self.compile())

    def _include(self, scope: ScopeName) -> SelectionQuery:
        return dataclasses.replace(self, scopes=(*self.scopes, scope))


class TmuxSelection:
    """Selection root namespace."""

    @staticmethod
    def server() -> SelectionQuery:
        """Start at server depth."""
        return SelectionQuery(("server",))


@dataclass(frozen=True, slots=True)
class StaticSelectionRunner:
    """Runner returning fixed field payloads."""

    values: SelectionPayload

    def run(self, plan: SelectionPlan) -> SelectionPayload:
        """Return values requested by a compiled plan."""
        return {
            field: self.values[field] for field in plan.fields if field in self.values
        }
