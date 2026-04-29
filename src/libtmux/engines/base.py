"""Core abstractions for libtmux command engines."""

from __future__ import annotations

import pathlib
import typing as t
from dataclasses import dataclass


@dataclass(frozen=True)
class CommandRequest:
    """Description of a tmux command invocation."""

    args: tuple[str, ...]
    tmux_bin: str | None = None

    @classmethod
    def from_args(
        cls,
        *args: t.Any,
        tmux_bin: str | pathlib.Path | None = None,
    ) -> CommandRequest:
        """Build a request from arbitrary command arguments."""
        return cls(
            args=tuple(str(arg) for arg in args),
            tmux_bin=str(tmux_bin) if tmux_bin is not None else None,
        )


@dataclass
class CommandResult:
    """Result of executing a tmux command."""

    cmd: list[str]
    stdout: list[str]
    stderr: list[str]
    returncode: int
    process: object | None = None


class TmuxEngine(t.Protocol):
    """Protocol for components that can execute tmux commands."""

    def run(self, request: CommandRequest) -> CommandResult:
        """Execute a tmux command and return a structured result."""
