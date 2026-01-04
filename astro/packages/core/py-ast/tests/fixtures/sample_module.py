"""Sample module for AST scanning."""

from __future__ import annotations

import dataclasses
import typing as t

CONSTANT: str = "value"


def greet(name: str) -> str:
    """Return a friendly greeting.

    Parameters
    ----------
    name : str
        Name to greet.

    Returns
    -------
    str
        Greeting string.
    """
    return f"hello {name}"


def _private() -> None:
    """Private helper."""


@dataclasses.dataclass
class Widget:
    """Widget model."""

    name: str
    size: int = 1

    def label(self) -> str:
        """Return a label.

        Returns
        -------
        str
            Label string.
        """
        return f"{self.name}:{self.size}"


class Container:
    """Container type."""

    count: int = 0

    def __init__(self, items: list[str]) -> None:
        """Create a container.

        Parameters
        ----------
        items : list[str]
            Items to store.
        """
        self.items = items

    @property
    def item_count(self) -> int:
        """Return count of items.

        Returns
        -------
        int
            Item count.
        """
        return len(self.items)

    async def refresh(self) -> None:
        """Refresh the container."""
        return None


def uses_typing(value: t.Any) -> t.Any:
    """Return provided value.

    Parameters
    ----------
    value : typing.Any
        Input value.

    Returns
    -------
    typing.Any
        Input value.
    """
    return value
