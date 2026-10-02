"""Explicit builder experiment for typed command chains."""

from __future__ import annotations

from .shared import (
    CommandCall,
    CommandSequence,
    new_window_call,
    split_window_call,
)


class Commands:
    """Completion-friendly command factory."""

    def new_window(
        self,
        *,
        window_name: str | None = None,
        detach: bool = True,
    ) -> CommandCall:
        """Build a ``new-window`` call."""
        return new_window_call(window_name=window_name, detach=detach)

    def split_window(
        self,
        *,
        horizontal: bool = False,
        percentage: int | None = None,
    ) -> CommandCall:
        """Build a ``split-window`` call."""
        return split_window_call(horizontal=horizontal, percentage=percentage)


commands = Commands()


def sequence(
    first: CommandCall,
    *rest: CommandCall,
) -> CommandSequence:
    """Create an immutable command sequence expression."""
    return CommandSequence((first, *rest))
