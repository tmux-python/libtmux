"""Deferred query-command plan experiment with typed targets."""

from __future__ import annotations

import collections.abc as cabc
import dataclasses
import typing as t
from dataclasses import dataclass

from .shared import Arg, CommandCall, CommandResultLike, CommandRunner

OrderField: t.TypeAlias = t.Literal["pane_id", "pane_index", "title"]
ResultT = t.TypeVar("ResultT")
MappedT = t.TypeVar("MappedT")


class NoCommandsResolved(RuntimeError):
    """Raised when a deferred plan resolves to no concrete commands."""


@dataclass(frozen=True, slots=True)
class PaneTarget:
    """Typed tmux pane target."""

    value: str

    @classmethod
    def coerce(cls, target: str | PaneTarget) -> PaneTarget:
        """Normalize raw pane target text into a typed target."""
        if isinstance(target, str):
            return cls(target)
        return target

    def __str__(self) -> str:
        """Render as the tmux target value."""
        return self.value


@dataclass(frozen=True, slots=True)
class WindowTarget:
    """Typed tmux window target."""

    value: str

    @classmethod
    def coerce(cls, target: str | WindowTarget) -> WindowTarget:
        """Normalize raw window target text into a typed target."""
        if isinstance(target, str):
            return cls(target)
        return target

    def __str__(self) -> str:
        """Render as the tmux target value."""
        return self.value


@dataclass(frozen=True, slots=True)
class SessionTarget:
    """Typed tmux session target."""

    value: str

    @classmethod
    def coerce(cls, target: str | SessionTarget) -> SessionTarget:
        """Normalize raw session target text into a typed target."""
        if isinstance(target, str):
            return cls(target)
        return target

    def __str__(self) -> str:
        """Render as the tmux target value."""
        return self.value


class CommandValue:
    """Base for command values created by deferred query plans."""

    def to_call(self) -> CommandCall:
        """Compile the command value into a shared command call."""
        raise NotImplementedError

    def argv(self) -> tuple[str, ...]:
        """Render this command as tmux argv tokens."""
        return self.to_call().argv()


CommandLike: t.TypeAlias = CommandValue | CommandCall
IntoCommands: t.TypeAlias = CommandLike | cabc.Iterable[CommandLike]


@dataclass(frozen=True, slots=True)
class SendKeys(CommandValue):
    """Command value for ``send-keys``."""

    target: PaneTarget
    command: str
    enter: bool = False

    def to_call(self) -> CommandCall:
        """Compile to a shared command call."""
        args: list[Arg] = [self.command]
        if self.enter:
            args.append("Enter")
        return CommandCall("send-keys", tuple(args), target=self.target.value)


@dataclass(frozen=True, slots=True)
class ResizePane(CommandValue):
    """Command value for ``resize-pane``."""

    target: PaneTarget
    height: int

    def to_call(self) -> CommandCall:
        """Compile to a shared command call."""
        return CommandCall("resize-pane", ("-y", self.height), target=self.target.value)


@dataclass(frozen=True, slots=True)
class SelectLayout(CommandValue):
    """Command value for ``select-layout``."""

    target: WindowTarget
    layout: str

    def to_call(self) -> CommandCall:
        """Compile to a shared command call."""
        return CommandCall("select-layout", (self.layout,), target=self.target.value)


class BoundPaneCommands:
    """Pane command namespace bound to a typed pane target."""

    def __init__(self, target: PaneTarget) -> None:
        """Store the pane target used by every command."""
        self.target = target

    def send_keys(self, command: str, *, enter: bool = False) -> SendKeys:
        """Build a target-bound ``send-keys`` command."""
        return SendKeys(target=self.target, command=command, enter=enter)

    def resize_pane(self, *, height: int) -> ResizePane:
        """Build a target-bound ``resize-pane`` command."""
        return ResizePane(target=self.target, height=height)


class BoundWindowCommands:
    """Window command namespace bound to a typed window target."""

    def __init__(self, target: WindowTarget) -> None:
        """Store the window target used by every command."""
        self.target = target

    def select_layout(self, layout: str) -> SelectLayout:
        """Build a target-bound ``select-layout`` command."""
        return SelectLayout(target=self.target, layout=layout)


@dataclass(frozen=True, slots=True)
class PaneRef:
    """Typed pane row returned by the lazy pane query."""

    pane_id: PaneTarget
    window_id: WindowTarget
    session_id: SessionTarget
    pane_index: int
    active: bool
    title: str

    @property
    def cmd(self) -> BoundPaneCommands:
        """Return pane-scoped commands bound to this pane."""
        return BoundPaneCommands(self.pane_id)

    @property
    def window(self) -> BoundWindowCommands:
        """Return window-scoped commands bound to this pane's window."""
        return BoundWindowCommands(self.window_id)


CommandMapper: t.TypeAlias = cabc.Callable[[PaneRef], IntoCommands]


@dataclass(frozen=True, slots=True)
class TmuxSnapshot:
    """Pure tmux state used to resolve deferred command plans."""

    panes: tuple[PaneRef, ...]


class SnapshotProvider(t.Protocol):
    """Object that can provide a pure tmux snapshot."""

    def snapshot(self) -> TmuxSnapshot:
        """Return a tmux snapshot."""
        ...


class PlanRunner(CommandRunner, SnapshotProvider, t.Protocol):
    """Runner that can resolve queries and dispatch tmux commands."""


SnapshotSource: t.TypeAlias = TmuxSnapshot | SnapshotProvider


@dataclass(frozen=True, slots=True)
class PaneQuery:
    """Lazy pane query that can become a deferred command plan."""

    active_filter: bool | None = None
    ordering: OrderField | None = None
    limit_count: int | None = None

    def filter(self, *, active: bool) -> PaneQuery:
        """Return a query filtered by active state."""
        return dataclasses.replace(self, active_filter=active)

    def order_by(self, field: OrderField) -> PaneQuery:
        """Return a query ordered by a known pane field."""
        return dataclasses.replace(self, ordering=field)

    def limit(self, count: int) -> PaneQuery:
        """Return a query capped to ``count`` rows."""
        return dataclasses.replace(self, limit_count=count)

    def all(self, source: SnapshotSource) -> list[PaneRef]:
        """Evaluate the query against a snapshot source."""
        rows = list(_resolve_snapshot(source).panes)
        if self.active_filter is not None:
            rows = [row for row in rows if row.active is self.active_filter]
        if self.ordering is not None:
            ordering = self.ordering
            rows.sort(key=lambda row: _order_value(row, ordering))
        if self.limit_count is not None:
            rows = rows[: self.limit_count]
        return rows

    def first(self, source: SnapshotSource) -> PaneRef | None:
        """Evaluate the query and return its first row."""
        rows = self.limit(1).all(source)
        if not rows:
            return None
        return rows[0]

    def map(
        self,
        mapper: cabc.Callable[[PaneRef], MappedT],
    ) -> MappedPaneQuery[MappedT]:
        """Return a data transformation query."""
        return MappedPaneQuery(query=self, mapper=mapper)

    def each(self, mapper: CommandMapper) -> CommandPlan[None]:
        """Return a deferred side-effect command plan."""
        return self.flat_map(mapper)

    def flat_map(self, mapper: CommandMapper) -> CommandPlan[None]:
        """Return a deferred multi-command side-effect plan."""
        return CommandPlan(ForEach(query=self, mapper=mapper))


@dataclass(frozen=True, slots=True)
class MappedPaneQuery(t.Generic[MappedT]):
    """Data-only query transformation over pane refs."""

    query: PaneQuery
    mapper: cabc.Callable[[PaneRef], MappedT]

    def all(self, source: SnapshotSource) -> list[MappedT]:
        """Evaluate the query and transform every row."""
        return [self.mapper(row) for row in self.query.all(source)]

    def first(self, source: SnapshotSource) -> MappedT | None:
        """Evaluate the query and transform the first row."""
        row = self.query.first(source)
        if row is None:
            return None
        return self.mapper(row)


@dataclass(frozen=True, slots=True)
class ForEach:
    """Deferred query plus command mapper plan node."""

    query: PaneQuery
    mapper: CommandMapper


@dataclass(frozen=True, slots=True)
class CommandSequence:
    """Resolved non-empty sequence of command calls."""

    calls: tuple[CommandCall, ...]

    def __post_init__(self) -> None:
        """Reject empty resolved command sequences."""
        if not self.calls:
            msg = "command plan resolved to no commands"
            raise NoCommandsResolved(msg)

    def argvs(self) -> tuple[tuple[str, ...], ...]:
        """Render each command independently."""
        return tuple(call.argv() for call in self.calls)

    def argv(self) -> tuple[str, ...]:
        """Render one native tmux semicolon command sequence."""
        rendered: list[str] = []
        for index, call in enumerate(self.calls):
            if index:
                rendered.append(";")
            rendered.extend(call.argv())
        return tuple(rendered)

    def run(self, runner: CommandRunner) -> CommandResultLike:
        """Dispatch the sequence through one runner call."""
        argv = self.argv()
        return runner.cmd(argv[0], *argv[1:])


@dataclass(frozen=True, slots=True)
class CommandPlan(t.Generic[ResultT]):
    """Lazy command plan that resolves a query into commands."""

    node: ForEach

    def to_sequence(self, source: SnapshotSource) -> CommandSequence:
        """Resolve the query and compile mapped commands."""
        calls: list[CommandCall] = []
        for row in self.node.query.all(source):
            calls.extend(_to_calls(self.node.mapper(row)))
        if not calls:
            msg = "command plan resolved to no commands"
            raise NoCommandsResolved(msg)
        return CommandSequence(tuple(calls))

    def run(self: CommandPlan[None], runner: PlanRunner) -> None:
        """Resolve, compile, and execute the plan through one tmux dispatch."""
        try:
            sequence = self.to_sequence(runner)
        except NoCommandsResolved:
            return None
        sequence.run(runner)
        return None


def panes() -> PaneQuery:
    """Start a lazy pane query."""
    return PaneQuery()


def _resolve_snapshot(source: SnapshotSource) -> TmuxSnapshot:
    if isinstance(source, TmuxSnapshot):
        return source
    return source.snapshot()


def _order_value(row: PaneRef, field: OrderField) -> str | int:
    if field == "pane_id":
        return row.pane_id.value
    if field == "pane_index":
        return row.pane_index
    return row.title


def _to_calls(value: IntoCommands) -> tuple[CommandCall, ...]:
    if isinstance(value, CommandCall):
        return (value,)
    if isinstance(value, CommandValue):
        return (value.to_call(),)
    if isinstance(value, str | bytes):
        msg = "command mapper must return a command or iterable of commands"
        raise TypeError(msg)

    calls: list[CommandCall] = []
    try:
        iterator = iter(value)
    except TypeError as exc:
        msg = "command mapper must return a command or iterable of commands"
        raise TypeError(msg) from exc
    for item in iterator:
        calls.extend(_to_calls(item))
    return tuple(calls)
