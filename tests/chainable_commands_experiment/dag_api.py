"""Hamilton-style function DAG experiment for command sequences."""

from __future__ import annotations

import collections.abc as cabc
from dataclasses import dataclass

from .shared import CommandCall, CommandSequence

StepBuilder = cabc.Callable[[], CommandCall]


@dataclass(frozen=True, slots=True)
class CommandStep:
    """Named command-producing DAG step."""

    name: str
    builder: StepBuilder
    depends_on: tuple[str, ...] = ()

    def build(self) -> CommandCall:
        """Build this step's command call."""
        return self.builder()


def command_step(
    name: str,
    *,
    depends_on: tuple[str, ...] = (),
) -> cabc.Callable[[StepBuilder], CommandStep]:
    """Decorate a nullary function as a command DAG step."""

    def decorator(function: StepBuilder) -> CommandStep:
        return CommandStep(name=name, builder=function, depends_on=depends_on)

    return decorator


@dataclass(frozen=True, slots=True)
class CommandDag:
    """Small command DAG that compiles requested outputs to a sequence."""

    steps: tuple[CommandStep, ...]
    outputs: tuple[str, ...]

    def missing_dependencies(self) -> tuple[str, ...]:
        """Return dependency names absent from the DAG."""
        step_names = {step.name for step in self.steps}
        missing: list[str] = []
        for step in self.steps:
            for dependency in step.depends_on:
                if dependency not in step_names and dependency not in missing:
                    missing.append(dependency)
        return tuple(missing)

    def sequence(self) -> CommandSequence:
        """Build a command sequence for the requested outputs."""
        missing = self.missing_dependencies()
        if missing:
            msg = f"missing dependencies: {', '.join(missing)}"
            raise ValueError(msg)

        step_by_name = {step.name: step for step in self.steps}
        ordered: list[CommandCall] = []
        visited: set[str] = set()

        def visit(name: str) -> None:
            if name in visited:
                return
            step = step_by_name[name]
            for dependency in step.depends_on:
                visit(dependency)
            ordered.append(step.build())
            visited.add(name)

        for output in self.outputs:
            visit(output)
        return CommandSequence(tuple(ordered))
