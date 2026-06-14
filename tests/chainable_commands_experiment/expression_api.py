"""Ibis-style typed expression experiment."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

Scalar: t.TypeAlias = str | int | bool
Row: t.TypeAlias = dict[str, object]
FieldT = t.TypeVar("FieldT", bound=Scalar)


@dataclass(frozen=True, slots=True)
class Predicate:
    """Compiled comparison against one field."""

    field_name: str
    value: Scalar

    def compile(self) -> str:
        """Compile the predicate to a displayable expression."""
        return f"{self.field_name}={self.value}"


@dataclass(frozen=True, slots=True)
class Field(t.Generic[FieldT]):
    """Typed field expression."""

    name: str

    def eq(self, value: FieldT) -> Predicate:
        """Return an equality predicate for this field."""
        return Predicate(self.name, value)


SelectableField: t.TypeAlias = Field[str] | Field[int] | Field[bool]


@dataclass(frozen=True, slots=True)
class CompiledExpression:
    """Compiled table expression."""

    fields: tuple[str, ...]
    predicates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TableExpression:
    """Immutable table expression."""

    predicates: tuple[Predicate, ...] = ()
    fields: tuple[SelectableField, ...] = ()

    def where(self, predicate: Predicate) -> TableExpression:
        """Return an expression with another predicate."""
        return TableExpression((*self.predicates, predicate), self.fields)

    def select(self, *fields: SelectableField) -> TableExpression:
        """Return an expression with selected fields."""
        return TableExpression(self.predicates, fields)

    def compile(self) -> CompiledExpression:
        """Compile fields and predicates without executing them."""
        return CompiledExpression(
            fields=tuple(field.name for field in self.fields),
            predicates=tuple(predicate.compile() for predicate in self.predicates),
        )

    def execute(self, runner: ExpressionRunner) -> list[Row]:
        """Execute this expression against a runner."""
        return runner.execute(self)


class PaneTable:
    """Typed pane table expression root."""

    id = Field[str]("pane_id")
    title = Field[str]("pane_title")
    active = Field[bool]("pane_active")

    def where(self, predicate: Predicate) -> TableExpression:
        """Start a pane expression with a predicate."""
        return TableExpression().where(predicate)

    def select(self, *fields: SelectableField) -> TableExpression:
        """Start a pane expression with selected fields."""
        return TableExpression().select(*fields)


@dataclass(frozen=True, slots=True)
class ExpressionRunner:
    """Backend runner for expression materialization."""

    rows: tuple[Row, ...]

    def execute(self, expression: TableExpression) -> list[Row]:
        """Materialize rows matching an expression."""
        selected: list[Row] = []
        for row in self.rows:
            if not _matches(row, expression.predicates):
                continue
            selected.append(
                {
                    field.name: row[field.name]
                    for field in expression.fields
                    if field.name in row
                },
            )
        return selected


def _matches(row: Row, predicates: tuple[Predicate, ...]) -> bool:
    return all(
        row.get(predicate.field_name) == predicate.value for predicate in predicates
    )
