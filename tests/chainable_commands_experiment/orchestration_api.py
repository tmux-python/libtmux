"""Prefect-style orchestration experiment for deferred command tasks."""

from __future__ import annotations

import collections.abc as cabc
from dataclasses import dataclass

from .shared import CommandCall, CommandSequence

RenameArguments = tuple[str, str]
RenameTask = cabc.Callable[[str, str], CommandCall]


@dataclass(frozen=True, slots=True)
class SubmittedCommand:
    """Deferred command submission."""

    call: CommandCall


class CommandTask:
    """Typed command task with submit and map-style helpers."""

    def __init__(self, function: RenameTask) -> None:
        """Store a typed command factory."""
        self._function = function

    def submit(self, target: str, name: str) -> SubmittedCommand:
        """Submit one command for later sequencing."""
        return SubmittedCommand(self._function(target, name))

    def map(self, arguments: cabc.Iterable[RenameArguments]) -> list[SubmittedCommand]:
        """Submit many commands from an iterable of argument tuples."""
        return [self.submit(target, name) for target, name in arguments]


def rename_window(target: str, name: str) -> CommandCall:
    """Build a target-aware ``rename-window`` command."""
    return CommandCall("rename-window", (name,), target=target)


def submitted_sequence(submitted: cabc.Sequence[SubmittedCommand]) -> CommandSequence:
    """Collapse submitted commands to a native tmux sequence."""
    return CommandSequence(tuple(item.call for item in submitted))
