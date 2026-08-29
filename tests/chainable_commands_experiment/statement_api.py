"""SQLAlchemy-style generative command statement experiment."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

from .shared import Arg, CommandCall


@dataclass(frozen=True, slots=True)
class CommandStatement:
    """Immutable command statement executed later by a runner."""

    name: str
    args: tuple[Arg, ...] = ()
    target_value: str | int | None = None

    def target(self, target: str | int) -> CommandStatement:
        """Return a statement with a tmux target."""
        return dataclasses.replace(self, target_value=target)

    def flag(self, name: str, value: Arg | None = None) -> CommandStatement:
        """Return a statement with a command flag."""
        args = (*self.args, name) if value is None else (*self.args, name, value)
        return dataclasses.replace(self, args=args)

    def arg(self, value: Arg) -> CommandStatement:
        """Return a statement with one positional argument."""
        return dataclasses.replace(self, args=(*self.args, value))

    def to_call(self) -> CommandCall:
        """Compile the statement to the shared command-call IR."""
        return CommandCall(self.name, self.args, target=self.target_value)


@dataclass(frozen=True, slots=True)
class StatementResult:
    """Recorded statement execution result."""

    argv: tuple[str, ...]


@dataclass
class StatementRunner:
    """Runner that records executed statements."""

    executed: list[tuple[str, ...]] = field(default_factory=list)

    def execute(self, statement: CommandStatement) -> StatementResult:
        """Execute a statement at the explicit boundary."""
        argv = statement.to_call().argv()
        self.executed.append(argv)
        return StatementResult(argv)
