"""Context-manager experiment for typed command batches."""

from __future__ import annotations

import types

from typing_extensions import Self

from .shared import (
    CommandCall,
    CommandSequence,
    new_window_call,
    split_window_call,
)


class CommandBatch:
    """Accumulate explicit typed command methods inside a context manager."""

    def __init__(self) -> None:
        """Initialize an empty command batch."""
        self._calls: list[CommandCall] = []

    def __enter__(self) -> Self:
        """Enter the batch context."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> None:
        """Leave the batch context."""

    def add(self, call: CommandCall) -> CommandCall:
        """Append a call and return it for local use."""
        self._calls.append(call)
        return call

    def to_sequence(self) -> CommandSequence:
        """Return the accumulated calls as an immutable sequence."""
        return CommandSequence(tuple(self._calls))

    def new_window(
        self,
        *,
        window_name: str | None = None,
        detach: bool = True,
    ) -> CommandCall:
        """Add a ``new-window`` call."""
        return self.add(
            new_window_call(window_name=window_name, detach=detach),
        )

    def split_window(
        self,
        *,
        horizontal: bool = False,
        percentage: int | None = None,
    ) -> CommandCall:
        """Add a ``split-window`` call."""
        return self.add(
            split_window_call(horizontal=horizontal, percentage=percentage),
        )
