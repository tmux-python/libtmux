"""Core abstractions for libtmux command engines."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass
class CommandResult:
    """Result of executing a tmux command."""

    cmd: Sequence[str]
    stdout: list[str]
    stderr: list[str]
    returncode: int
    process: object | None = None


class TmuxEngine(Protocol):
    """Protocol for components that can execute tmux commands."""

    def run(self, *args: str | int) -> CommandResult:  # pragma: no cover
        """Execute a tmux command and return a :class:`CommandResult`.

        Implementations may rely on structural typing rather than inheritance.
        """
