"""Transparent auto-batch experiment for self-returning APIs."""

from __future__ import annotations

from dataclasses import dataclass

from typing_extensions import Self

from .shared import (
    Arg,
    CommandCall,
    CommandSequence,
    rename_window_call,
    select_layout_call,
    show_option_call,
)


class DeferredOutputUnavailable(RuntimeError):
    """Raised when a deferred command result is inspected before dispatch."""


@dataclass(frozen=True, slots=True)
class DeferredCommandResult:
    """Placeholder result returned by a transparent auto-batch target."""

    call: CommandCall

    @property
    def stdout(self) -> list[str]:
        """Reject immediate stdout access."""
        msg = "deferred command output is unavailable until the chain is run"
        raise DeferredOutputUnavailable(msg)

    @property
    def stderr(self) -> list[str]:
        """Reject immediate stderr access."""
        msg = "deferred command errors are unavailable until the chain is run"
        raise DeferredOutputUnavailable(msg)

    @property
    def returncode(self) -> int:
        """Reject immediate return-code access."""
        msg = "deferred command status is unavailable until the chain is run"
        raise DeferredOutputUnavailable(msg)


class AutoBatchTarget:
    """Small target object that accumulates existing ``cmd``-style calls."""

    def __init__(self) -> None:
        """Initialize an empty pending call list."""
        self._calls: list[CommandCall] = []

    def cmd(
        self,
        cmd: str,
        *args: Arg,
        target: str | int | None = None,
    ) -> DeferredCommandResult:
        """Add a command call instead of dispatching it."""
        call = CommandCall(cmd, args, target=target)
        self._calls.append(call)
        return DeferredCommandResult(call)

    def to_sequence(self) -> CommandSequence:
        """Return the accumulated calls as a sequence."""
        return CommandSequence(tuple(self._calls))

    def rename_window(self, new_name: str) -> Self:
        """Add a self-returning ``rename-window`` method."""
        call = rename_window_call(new_name)
        self._calls.append(call)
        return self

    def select_layout(self, layout: str) -> Self:
        """Add a self-returning ``select-layout`` method."""
        call = select_layout_call(layout)
        self._calls.append(call)
        return self

    def show_option(self, option_name: str) -> list[str]:
        """Demonstrate why immediate-output methods cannot auto-batch."""
        call = show_option_call(option_name)
        return self.cmd(call.name, *call.args).stdout
