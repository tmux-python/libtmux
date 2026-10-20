"""Shared typed command-sequence primitives for the experiments."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

Arg: t.TypeAlias = str | int
CommandScope: t.TypeAlias = t.Literal["server", "session", "window", "pane"]


class CommandResultLike(t.Protocol):
    """Small result protocol matching the libtmux command result surface."""

    stdout: list[str]
    stderr: list[str]
    returncode: int


class CommandRunner(t.Protocol):
    """Object capable of dispatching one tmux command argv."""

    def cmd(
        self,
        cmd: str,
        *args: Arg,
        target: str | int | None = None,
    ) -> CommandResultLike:
        """Dispatch a tmux command."""
        ...


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """Static metadata for a tmux command factory."""

    name: str
    scope: CommandScope
    chainable: bool = True


@dataclass(frozen=True, slots=True)
class CommandCall:
    """One typed tmux command call before subprocess dispatch."""

    name: str
    args: tuple[Arg, ...] = ()
    target: str | int | None = None

    def argv(self) -> tuple[str, ...]:
        """Render this call as tmux argv tokens."""
        rendered: list[str] = [self.name]
        if self.target is not None:
            rendered.extend(("-t", str(self.target)))
        rendered.extend(_render_arg(arg) for arg in self.args)
        return tuple(rendered)

    def then(self, other: CommandCall | CommandSequence) -> CommandSequence:
        """Return a sequence with another call or sequence appended."""
        if isinstance(other, CommandCall):
            return CommandSequence((self, other))
        return CommandSequence((self, *other.calls))

    def __rshift__(self, other: CommandCall | CommandSequence) -> CommandSequence:
        """Compose command calls with ``>>``."""
        return self.then(other)


@dataclass(frozen=True, slots=True)
class CommandSequence:
    """Ordered native tmux command sequence."""

    calls: tuple[CommandCall, ...]

    def __post_init__(self) -> None:
        """Reject empty sequences."""
        if not self.calls:
            msg = "CommandSequence requires at least one call"
            raise ValueError(msg)

    def argv(self) -> tuple[str, ...]:
        """Render the full sequence with tmux semicolon separators."""
        rendered: list[str] = []
        for index, call in enumerate(self.calls):
            if index:
                rendered.append(";")
            rendered.extend(call.argv())
        return tuple(rendered)

    def then(self, other: CommandCall | CommandSequence) -> CommandSequence:
        """Return a sequence with another call or sequence appended."""
        if isinstance(other, CommandCall):
            return CommandSequence((*self.calls, other))
        return CommandSequence((*self.calls, *other.calls))

    def __rshift__(self, other: CommandCall | CommandSequence) -> CommandSequence:
        """Compose command sequences with ``>>``."""
        return self.then(other)

    def run(self, runner: CommandRunner) -> CommandResultLike:
        """Dispatch the sequence through one runner call."""
        argv = self.argv()
        return runner.cmd(argv[0], *argv[1:])


def new_window_call(
    window_name: str | None = None,
    *,
    detach: bool = True,
) -> CommandCall:
    """Build a ``new-window`` call."""
    args: list[Arg] = []
    if detach:
        args.append("-d")
    if window_name is not None:
        args.extend(("-n", window_name))
    return CommandCall("new-window", tuple(args))


def split_window_call(
    *,
    horizontal: bool = False,
    percentage: int | None = None,
) -> CommandCall:
    """Build a ``split-window`` call."""
    args: list[Arg] = []
    if horizontal:
        args.append("-h")
    if percentage is not None:
        args.extend(("-p", percentage))
    return CommandCall("split-window", tuple(args))


def rename_window_call(new_name: str) -> CommandCall:
    """Build a ``rename-window`` call."""
    return CommandCall("rename-window", (new_name,))


def select_layout_call(layout: str) -> CommandCall:
    """Build a ``select-layout`` call."""
    return CommandCall("select-layout", (layout,))


def show_option_call(option_name: str) -> CommandCall:
    """Build a ``show-option`` call."""
    return CommandCall("show-option", ("-gqv", option_name))


def _render_arg(arg: Arg) -> str:
    text = str(arg)
    if text.endswith(";"):
        return f"{text[:-1]}\\;"
    return text
