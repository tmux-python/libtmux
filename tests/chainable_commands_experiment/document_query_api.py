"""Beanie-style document query experiment for command metadata."""

from __future__ import annotations

import collections.abc as cabc
from dataclasses import dataclass

from .shared import CommandScope


@dataclass(frozen=True, slots=True)
class CommandDocument:
    """Document-shaped command metadata."""

    name: str
    scope: CommandScope
    chainable: bool


class CommandDocumentQuery:
    """Immutable query over command metadata documents."""

    def __init__(
        self,
        documents: cabc.Iterable[CommandDocument],
        *,
        scope: CommandScope | None = None,
        chainable: bool | None = None,
        name: str | None = None,
    ) -> None:
        """Store the document set and filters."""
        self._documents = tuple(documents)
        self._scope = scope
        self._chainable = chainable
        self._name = name

    def where(
        self,
        *,
        scope: CommandScope | None = None,
        chainable: bool | None = None,
    ) -> CommandDocumentQuery:
        """Return a query filtered by document fields."""
        return CommandDocumentQuery(
            self._documents,
            scope=self._scope if scope is None else scope,
            chainable=self._chainable if chainable is None else chainable,
            name=self._name,
        )

    def where_name(self, name: str) -> CommandDocumentQuery:
        """Return a query filtered by command name."""
        return CommandDocumentQuery(
            self._documents,
            scope=self._scope,
            chainable=self._chainable,
            name=name,
        )

    def all(self) -> list[CommandDocument]:
        """Return all matching command documents."""
        return [document for document in self._documents if self._matches(document)]

    def _matches(self, document: CommandDocument) -> bool:
        if self._scope is not None and document.scope != self._scope:
            return False
        if self._chainable is not None and document.chainable is not self._chainable:
            return False
        return self._name is None or document.name == self._name
