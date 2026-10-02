"""LangChain-style runnable experiment for command composition."""

from __future__ import annotations

import collections.abc as cabc
import typing as t
from dataclasses import dataclass, field

from .shared import Arg, CommandCall, CommandRunner

InputT = t.TypeVar("InputT")
OutputT = t.TypeVar("OutputT")
NextT = t.TypeVar("NextT")


@dataclass(slots=True)
class RunRecord:
    """Materialized result from a runnable command dispatch."""

    command: str
    args: tuple[Arg, ...]
    target: str | int | None
    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)
    returncode: int = 0


class RunnableCommand(t.Generic[InputT, OutputT]):
    """Small invokable, batchable, composable command unit."""

    def __init__(
        self,
        invoke: cabc.Callable[[InputT, CommandRunner], OutputT],
    ) -> None:
        """Store the typed invocation function."""
        self._invoke = invoke

    def invoke(self, input_value: InputT, runner: CommandRunner) -> OutputT:
        """Run the command unit for one input."""
        return self._invoke(input_value, runner)

    def batch(
        self,
        input_values: cabc.Iterable[InputT],
        runner: CommandRunner,
    ) -> list[OutputT]:
        """Run the command unit for many inputs."""
        return [self.invoke(input_value, runner) for input_value in input_values]

    def stream(
        self,
        input_value: InputT,
        runner: CommandRunner,
    ) -> cabc.Iterator[OutputT]:
        """Yield the single result through a streaming-shaped API."""
        yield self.invoke(input_value, runner)

    def then(
        self,
        next_command: RunnableCommand[OutputT, NextT],
    ) -> RunnableCommand[InputT, NextT]:
        """Compose this runnable with a following runnable."""

        def invoke(input_value: InputT, runner: CommandRunner) -> NextT:
            return next_command.invoke(self.invoke(input_value, runner), runner)

        return RunnableCommand(invoke)

    def __rshift__(
        self,
        next_command: RunnableCommand[OutputT, NextT],
    ) -> RunnableCommand[InputT, NextT]:
        """Compose runnable commands with ``>>``."""
        return self.then(next_command)


def target_capture_call() -> RunnableCommand[str, CommandCall]:
    """Build a runnable that maps a target pane to a capture command."""

    def invoke(target: str, runner: CommandRunner) -> CommandCall:
        del runner
        return CommandCall("capture-pane", ("-p",), target=target)

    return RunnableCommand(invoke)


def run_command() -> RunnableCommand[CommandCall, RunRecord]:
    """Build a runnable that dispatches a command call."""

    def invoke(call: CommandCall, runner: CommandRunner) -> RunRecord:
        result = runner.cmd(call.name, *call.args, target=call.target)
        return RunRecord(
            command=call.name,
            args=call.args,
            target=call.target,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )

    return RunnableCommand(invoke)


def render_argv() -> RunnableCommand[CommandCall, tuple[str, ...]]:
    """Build a runnable that renders a command call without dispatching it."""

    def invoke(call: CommandCall, runner: CommandRunner) -> tuple[str, ...]:
        del runner
        return call.argv()

    return RunnableCommand(invoke)
