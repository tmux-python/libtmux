"""Explicit command-object experiment for typed command values."""

from __future__ import annotations

import types
import typing as t
from dataclasses import dataclass

from typing_extensions import Self

from .shared import (
    Arg,
    CommandCall,
    CommandResultLike,
    CommandRunner,
    CommandSequence as SharedCommandSequence,
    CommandSpec,
)


class CommandValue:
    """Base for command objects that are values before they are effects."""

    spec: t.ClassVar[CommandSpec]

    def to_call(self) -> CommandCall:
        """Compile this command object to the shared command-call IR."""
        raise NotImplementedError

    def argv(self) -> tuple[str, ...]:
        """Render this command object as tmux argv tokens."""
        return self.to_call().argv()

    def run(self, runner: CommandRunner) -> CommandResultLike:
        """Dispatch this command object through an explicit runner boundary."""
        call = self.to_call()
        return runner.cmd(call.name, *call.args, target=call.target)

    def then(self, other: Commandish) -> CommandObjectSequence:
        """Compose this command object with another command value."""
        return CommandObjectSequence((self.to_call(),)).then(other)

    def __rshift__(self, other: Commandish) -> CommandObjectSequence:
        """Compose command objects with ``>>``."""
        return self.then(other)


Commandish: t.TypeAlias = CommandValue | CommandCall | SharedCommandSequence


@dataclass(frozen=True, slots=True)
class CommandObjectSequence(SharedCommandSequence):
    """Command sequence that also accepts command-object values."""

    def then(self, other: Commandish) -> CommandObjectSequence:
        """Return a sequence with another command-ish value appended."""
        return CommandObjectSequence((*self.calls, *_to_sequence(other).calls))

    def __rshift__(self, other: Commandish) -> CommandObjectSequence:
        """Compose command-object sequences with ``>>``."""
        return self.then(other)


class ServerCmd:
    """Explicit command objects for server-scoped commands."""

    @dataclass(frozen=True, slots=True)
    class SetOption(CommandValue):
        """Command object for ``set-option``."""

        option_name: str
        value: str
        target: str | int | None = None

        spec: t.ClassVar[CommandSpec] = CommandSpec(
            name="set-option",
            scope="server",
        )

        def to_call(self) -> CommandCall:
            """Compile to a shared command call."""
            return CommandCall(
                self.spec.name,
                ("-gq", self.option_name, self.value),
                target=self.target,
            )

    @dataclass(frozen=True, slots=True)
    class ShowOption(CommandValue):
        """Command object for ``show-option``."""

        option_name: str
        target: str | int | None = None

        spec: t.ClassVar[CommandSpec] = CommandSpec(
            name="show-option",
            scope="server",
        )

        def to_call(self) -> CommandCall:
            """Compile to a shared command call."""
            return CommandCall(
                self.spec.name,
                ("-gqv", self.option_name),
                target=self.target,
            )

    @dataclass(frozen=True, slots=True)
    class HasSession(CommandValue):
        """Command object for ``has-session``."""

        session_name: str

        spec: t.ClassVar[CommandSpec] = CommandSpec(
            name="has-session",
            scope="server",
        )

        def to_call(self) -> CommandCall:
            """Compile to a shared command call."""
            return CommandCall(self.spec.name, ("-t", self.session_name))


class SessionCmd:
    """Explicit command objects for session-scoped commands."""

    @dataclass(frozen=True, slots=True)
    class NewWindow(CommandValue):
        """Command object for ``new-window``."""

        target: str | int | None = None
        window_name: str | None = None
        detach: bool = True

        spec: t.ClassVar[CommandSpec] = CommandSpec(
            name="new-window",
            scope="session",
        )

        def to_call(self) -> CommandCall:
            """Compile to a shared command call."""
            args: list[Arg] = []
            if self.detach:
                args.append("-d")
            if self.window_name is not None:
                args.extend(("-n", self.window_name))
            return CommandCall(self.spec.name, tuple(args), target=self.target)


class WindowCmd:
    """Explicit command objects for window-scoped commands."""

    @dataclass(frozen=True, slots=True)
    class RenameWindow(CommandValue):
        """Command object for ``rename-window``."""

        name: str
        target: str | int | None = None

        spec: t.ClassVar[CommandSpec] = CommandSpec(
            name="rename-window",
            scope="window",
        )

        def to_call(self) -> CommandCall:
            """Compile to a shared command call."""
            return CommandCall(self.spec.name, (self.name,), target=self.target)

    @dataclass(frozen=True, slots=True)
    class SelectLayout(CommandValue):
        """Command object for ``select-layout``."""

        layout: str
        target: str | int | None = None

        spec: t.ClassVar[CommandSpec] = CommandSpec(
            name="select-layout",
            scope="window",
        )

        def to_call(self) -> CommandCall:
            """Compile to a shared command call."""
            return CommandCall(self.spec.name, (self.layout,), target=self.target)


class PaneCmd:
    """Explicit command objects for pane-scoped commands."""

    @dataclass(frozen=True, slots=True)
    class SplitWindow(CommandValue):
        """Command object for ``split-window``."""

        target: str | int | None = None
        horizontal: bool = False
        percentage: int | None = None

        spec: t.ClassVar[CommandSpec] = CommandSpec(
            name="split-window",
            scope="pane",
        )

        def to_call(self) -> CommandCall:
            """Compile to a shared command call."""
            args: list[Arg] = []
            if self.horizontal:
                args.append("-h")
            if self.percentage is not None:
                args.extend(("-p", self.percentage))
            return CommandCall(self.spec.name, tuple(args), target=self.target)

    @dataclass(frozen=True, slots=True)
    class CapturePane(CommandValue):
        """Command object for ``capture-pane``."""

        target: str | int | None = None
        print_output: bool = True

        spec: t.ClassVar[CommandSpec] = CommandSpec(
            name="capture-pane",
            scope="pane",
        )

        def to_call(self) -> CommandCall:
            """Compile to a shared command call."""
            args: tuple[Arg, ...] = ("-p",) if self.print_output else ()
            return CommandCall(self.spec.name, args, target=self.target)


def CommandSequenceBuilder(
    first: CommandValue,
    *rest: CommandValue,
) -> CommandObjectSequence:
    """Build a native tmux command sequence from command objects."""
    return CommandObjectSequence(
        tuple(command.to_call() for command in (first, *rest)),
    )


class CommandBatch:
    """Accumulate command-object factories in explicit namespaces."""

    def __init__(self) -> None:
        """Initialize command namespaces."""
        self._commands: list[CommandValue] = []
        self.server = ServerCommands(self)
        self.session = SessionCommands(self)
        self.window = WindowCommands(self)
        self.pane = PaneCommands(self)

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

    def add(self, command: CommandT) -> CommandT:
        """Add a command object and return its concrete type."""
        self._commands.append(command)
        return command

    def to_sequence(self) -> CommandObjectSequence:
        """Return accumulated commands as a native tmux command sequence."""
        return CommandSequenceBuilder(*self._commands)


CommandT = t.TypeVar("CommandT", bound=CommandValue)


class ServerCommands:
    """Typed namespace for server command objects."""

    def __init__(self, batch: CommandBatch) -> None:
        """Store the parent batch."""
        self._batch = batch

    def set_option(
        self,
        *,
        option_name: str,
        value: str,
        target: str | int | None = None,
    ) -> ServerCmd.SetOption:
        """Add a ``set-option`` command object."""
        return self._batch.add(
            ServerCmd.SetOption(
                option_name=option_name,
                value=value,
                target=target,
            ),
        )


class SessionCommands:
    """Typed namespace for session command objects."""

    def __init__(self, batch: CommandBatch) -> None:
        """Store the parent batch."""
        self._batch = batch

    def new_window(
        self,
        *,
        target: str | int | None = None,
        window_name: str | None = None,
        detach: bool = True,
    ) -> SessionCmd.NewWindow:
        """Add a ``new-window`` command object."""
        return self._batch.add(
            SessionCmd.NewWindow(
                target=target,
                window_name=window_name,
                detach=detach,
            ),
        )


class WindowCommands:
    """Typed namespace for window command objects."""

    def __init__(self, batch: CommandBatch) -> None:
        """Store the parent batch."""
        self._batch = batch

    def rename_window(
        self,
        *,
        name: str,
        target: str | int | None = None,
    ) -> WindowCmd.RenameWindow:
        """Add a ``rename-window`` command object."""
        return self._batch.add(WindowCmd.RenameWindow(name=name, target=target))

    def select_layout(
        self,
        *,
        layout: str,
        target: str | int | None = None,
    ) -> WindowCmd.SelectLayout:
        """Add a ``select-layout`` command object."""
        return self._batch.add(WindowCmd.SelectLayout(layout=layout, target=target))


class PaneCommands:
    """Typed namespace for pane command objects."""

    def __init__(self, batch: CommandBatch) -> None:
        """Store the parent batch."""
        self._batch = batch

    def split_window(
        self,
        *,
        target: str | int | None = None,
        horizontal: bool = False,
        percentage: int | None = None,
    ) -> PaneCmd.SplitWindow:
        """Add a ``split-window`` command object."""
        return self._batch.add(
            PaneCmd.SplitWindow(
                target=target,
                horizontal=horizontal,
                percentage=percentage,
            ),
        )


def _to_sequence(command: Commandish) -> SharedCommandSequence:
    if isinstance(command, SharedCommandSequence):
        return command
    if isinstance(command, CommandCall):
        return SharedCommandSequence((command,))
    return SharedCommandSequence((command.to_call(),))
