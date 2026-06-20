"""Typed, target-safe deferred query-command plans.

A plan starts from a lazy :class:`PaneQuery`, resolves it against a pure
:class:`TmuxSnapshot`, maps each typed :class:`PaneRef` row to one or more
commands, and compiles the result into a single
:class:`~libtmux._experimental.chain.ir.CommandChain` -- which
dispatches once. Targets are typed (:class:`PaneTarget`, :class:`WindowTarget`,
:class:`SessionTarget`), so a row-bound command namespace cannot mis-target a
command.

Compilation (:meth:`CommandPlan.to_chain`) is a pure function of the
snapshot, so a plan can be inspected in memory -- no tmux required -- and only
:meth:`CommandPlan.run` touches a live server.

Note
----
This is an **experimental** API, not covered by the project's versioning policy.
It may change or be removed between any releases without notice.
"""

from __future__ import annotations

import collections.abc as cabc
import dataclasses
import typing as t
from dataclasses import dataclass

from libtmux._experimental.chain.chain import ChainabilityError, is_chainable
from libtmux._experimental.chain.ir import (
    Arg,
    CommandCall,
    CommandChain,
    CommandRunner,
)

OrderField: t.TypeAlias = t.Literal["pane_id", "pane_index", "title"]
"""A :class:`PaneRef` field a query may order by."""

MappedT = t.TypeVar("MappedT")


class NoCommandsResolved(RuntimeError):
    """Raised when a deferred plan resolves to no concrete commands."""


@dataclass(frozen=True, slots=True)
class PaneTarget:
    """A typed tmux pane target (e.g. ``%1``).

    Examples
    --------
    >>> PaneTarget("%1")
    PaneTarget(value='%1')
    >>> str(PaneTarget("%1"))
    '%1'
    """

    value: str

    @classmethod
    def coerce(cls, target: str | PaneTarget) -> PaneTarget:
        """Normalize raw pane-target text into a typed target.

        Examples
        --------
        >>> PaneTarget.coerce("%2")
        PaneTarget(value='%2')
        >>> PaneTarget.coerce(PaneTarget("%2"))
        PaneTarget(value='%2')
        """
        if isinstance(target, str):
            return cls(target)
        return target

    def __str__(self) -> str:
        """Render as the tmux target value."""
        return self.value


@dataclass(frozen=True, slots=True)
class WindowTarget:
    """A typed tmux window target (e.g. ``@1``).

    Examples
    --------
    >>> str(WindowTarget("@1"))
    '@1'
    """

    value: str

    @classmethod
    def coerce(cls, target: str | WindowTarget) -> WindowTarget:
        """Normalize raw window-target text into a typed target.

        Examples
        --------
        >>> WindowTarget.coerce("@1")
        WindowTarget(value='@1')
        """
        if isinstance(target, str):
            return cls(target)
        return target

    def __str__(self) -> str:
        """Render as the tmux target value."""
        return self.value


@dataclass(frozen=True, slots=True)
class SessionTarget:
    """A typed tmux session target (e.g. ``$0``).

    Examples
    --------
    >>> str(SessionTarget("$0"))
    '$0'
    """

    value: str

    @classmethod
    def coerce(cls, target: str | SessionTarget) -> SessionTarget:
        """Normalize raw session-target text into a typed target.

        Examples
        --------
        >>> SessionTarget.coerce("$0")
        SessionTarget(value='$0')
        """
        if isinstance(target, str):
            return cls(target)
        return target

    def __str__(self) -> str:
        """Render as the tmux target value."""
        return self.value


class CommandValue:
    """Base for typed command values produced by a deferred plan.

    Subclasses carry their own typed target and compile to an
    :class:`~libtmux._experimental.chain.ir.CommandCall`.
    """

    def to_call(self) -> CommandCall:
        """Compile this command value into a shared command call."""
        raise NotImplementedError

    def argv(self) -> tuple[str, ...]:
        """Render this command value as tmux argv tokens.

        Examples
        --------
        >>> SendKeys(PaneTarget("%1"), "clear", enter=True).argv()
        ('send-keys', '-t', '%1', 'clear', 'Enter')
        """
        return self.to_call().argv()


CommandLike: t.TypeAlias = "CommandValue | CommandCall"
IntoCommands: t.TypeAlias = "CommandLike | cabc.Iterable[CommandLike]"


@dataclass(frozen=True, slots=True)
class SendKeys(CommandValue):
    """A typed ``send-keys`` command bound to a pane.

    Examples
    --------
    >>> SendKeys(PaneTarget("%1"), "clear", enter=True).argv()
    ('send-keys', '-t', '%1', 'clear', 'Enter')
    """

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
    """A typed ``resize-pane`` command bound to a pane.

    Examples
    --------
    >>> ResizePane(PaneTarget("%1"), height=20).argv()
    ('resize-pane', '-t', '%1', '-y', '20')
    """

    target: PaneTarget
    height: int

    def to_call(self) -> CommandCall:
        """Compile to a shared command call."""
        return CommandCall(
            "resize-pane",
            ("-y", self.height),
            target=self.target.value,
        )


@dataclass(frozen=True, slots=True)
class SelectLayout(CommandValue):
    """A typed ``select-layout`` command bound to a window.

    Examples
    --------
    >>> SelectLayout(WindowTarget("@1"), "even-horizontal").argv()
    ('select-layout', '-t', '@1', 'even-horizontal')
    """

    target: WindowTarget
    layout: str

    def to_call(self) -> CommandCall:
        """Compile to a shared command call."""
        return CommandCall("select-layout", (self.layout,), target=self.target.value)


class BoundPaneCommands:
    """Pane command namespace bound to one typed pane target.

    Examples
    --------
    >>> BoundPaneCommands(PaneTarget("%1")).send_keys("clear", enter=True).argv()
    ('send-keys', '-t', '%1', 'clear', 'Enter')
    """

    def __init__(self, target: PaneTarget) -> None:
        self.target = target

    def send_keys(self, command: str, *, enter: bool = False) -> SendKeys:
        """Build a target-bound ``send-keys`` command."""
        return SendKeys(target=self.target, command=command, enter=enter)

    def resize_pane(self, *, height: int) -> ResizePane:
        """Build a target-bound ``resize-pane`` command."""
        return ResizePane(target=self.target, height=height)


class BoundWindowCommands:
    """Window command namespace bound to one typed window target.

    Examples
    --------
    >>> BoundWindowCommands(WindowTarget("@1")).select_layout("tiled").argv()
    ('select-layout', '-t', '@1', 'tiled')
    """

    def __init__(self, target: WindowTarget) -> None:
        self.target = target

    def select_layout(self, layout: str) -> SelectLayout:
        """Build a target-bound ``select-layout`` command."""
        return SelectLayout(target=self.target, layout=layout)


@dataclass(frozen=True, slots=True)
class PaneRef:
    """A typed pane row returned by a pane query.

    The ``cmd`` and ``window`` namespaces are pre-bound to this row's typed
    targets, so commands built from a row cannot mis-target.

    Examples
    --------
    >>> pane = PaneRef(
    ...     pane_id=PaneTarget("%1"),
    ...     window_id=WindowTarget("@1"),
    ...     session_id=SessionTarget("$0"),
    ...     pane_index=0,
    ...     active=True,
    ...     title="editor",
    ... )
    >>> pane.cmd.send_keys("clear", enter=True).argv()
    ('send-keys', '-t', '%1', 'clear', 'Enter')
    >>> pane.window.select_layout("tiled").argv()
    ('select-layout', '-t', '@1', 'tiled')
    """

    pane_id: PaneTarget
    window_id: WindowTarget
    session_id: SessionTarget
    pane_index: int
    active: bool
    title: str

    @property
    def cmd(self) -> BoundPaneCommands:
        """Pane-scoped commands bound to this pane."""
        return BoundPaneCommands(self.pane_id)

    @property
    def window(self) -> BoundWindowCommands:
        """Window-scoped commands bound to this pane's window."""
        return BoundWindowCommands(self.window_id)


CommandMapper: t.TypeAlias = cabc.Callable[[PaneRef], IntoCommands]


@dataclass(frozen=True, slots=True)
class TmuxSnapshot:
    """A pure snapshot of tmux pane state used to resolve plans.

    Examples
    --------
    >>> snapshot = TmuxSnapshot(panes=())
    >>> snapshot.panes
    ()
    """

    panes: tuple[PaneRef, ...]


class SnapshotProvider(t.Protocol):
    """Object that can provide a pure tmux snapshot."""

    def snapshot(self) -> TmuxSnapshot:
        """Return a tmux snapshot."""
        ...


class PlanRunner(CommandRunner, SnapshotProvider, t.Protocol):
    """A runner that can both resolve snapshots and dispatch commands."""


SnapshotSource: t.TypeAlias = "TmuxSnapshot | SnapshotProvider"


@dataclass(frozen=True, slots=True)
class PaneQuery:
    """A lazy pane query that can become a deferred command plan.

    Examples
    --------
    >>> snapshot = TmuxSnapshot(
    ...     panes=(
    ...         PaneRef(PaneTarget("%1"), WindowTarget("@1"), SessionTarget("$0"),
    ...                 pane_index=0, active=True, title="editor"),
    ...         PaneRef(PaneTarget("%2"), WindowTarget("@1"), SessionTarget("$0"),
    ...                 pane_index=1, active=False, title="logs"),
    ...     ),
    ... )
    >>> [p.pane_id.value for p in panes().filter(active=True).all(snapshot)]
    ['%1']
    """

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
        """Evaluate the query against a snapshot source.

        Examples
        --------
        >>> snapshot = TmuxSnapshot(
        ...     panes=(
        ...         PaneRef(PaneTarget("%2"), WindowTarget("@1"), SessionTarget("$0"),
        ...                 pane_index=1, active=True, title="logs"),
        ...         PaneRef(PaneTarget("%1"), WindowTarget("@1"), SessionTarget("$0"),
        ...                 pane_index=0, active=True, title="editor"),
        ...     ),
        ... )
        >>> [p.pane_id.value for p in panes().order_by("pane_index").all(snapshot)]
        ['%1', '%2']
        """
        rows = list(_resolve_snapshot(source).panes)
        if self.active_filter is not None:
            rows = [row for row in rows if row.active == self.active_filter]
        if self.ordering is not None:
            ordering = self.ordering
            rows.sort(key=lambda row: _order_value(row, ordering))
        if self.limit_count is not None:
            rows = rows[: self.limit_count]
        return rows

    def first(self, source: SnapshotSource) -> PaneRef | None:
        """Evaluate the query and return its first row, or ``None``."""
        rows = self.limit(1).all(source)
        if not rows:
            return None
        return rows[0]

    def map(
        self,
        mapper: cabc.Callable[[PaneRef], MappedT],
    ) -> MappedPaneQuery[MappedT]:
        """Return a data-only transformation query (no commands)."""
        return MappedPaneQuery(query=self, mapper=mapper)

    def commands(self, mapper: CommandMapper) -> CommandPlan:
        """Return a deferred plan where each row maps to one or more commands.

        Examples
        --------
        >>> snapshot = TmuxSnapshot(
        ...     panes=(
        ...         PaneRef(PaneTarget("%1"), WindowTarget("@1"), SessionTarget("$0"),
        ...                 pane_index=0, active=True, title="editor"),
        ...     ),
        ... )
        >>> plan = panes().commands(
        ...     lambda pane: (
        ...         pane.cmd.resize_pane(height=10),
        ...         pane.window.select_layout("tiled"),
        ...     ),
        ... )
        >>> compiled = plan.to_chain(snapshot).argvs()
        >>> compiled[0]
        ('resize-pane', '-t', '%1', '-y', '10')
        >>> compiled[1]
        ('select-layout', '-t', '@1', 'tiled')
        """
        return CommandPlan(_CommandPlanNode(query=self, mapper=mapper))


@dataclass(frozen=True, slots=True)
class MappedPaneQuery(t.Generic[MappedT]):
    """A data-only query transformation over pane rows.

    Examples
    --------
    >>> snapshot = TmuxSnapshot(
    ...     panes=(
    ...         PaneRef(PaneTarget("%1"), WindowTarget("@1"), SessionTarget("$0"),
    ...                 pane_index=0, active=True, title="editor"),
    ...     ),
    ... )
    >>> panes().map(lambda pane: pane.title).all(snapshot)
    ['editor']
    """

    query: PaneQuery
    mapper: cabc.Callable[[PaneRef], MappedT]

    def all(self, source: SnapshotSource) -> list[MappedT]:
        """Evaluate the query and transform every row."""
        return [self.mapper(row) for row in self.query.all(source)]

    def first(self, source: SnapshotSource) -> MappedT | None:
        """Evaluate the query and transform the first row, or ``None``."""
        row = self.query.first(source)
        if row is None:
            return None
        return self.mapper(row)


@dataclass(frozen=True, slots=True)
class _CommandPlanNode:
    """A deferred query plus a command mapper (an unresolved plan node)."""

    query: PaneQuery
    mapper: CommandMapper


@dataclass(frozen=True, slots=True)
class CommandPlan:
    """A lazy command plan that resolves a query into a command sequence.

    Examples
    --------
    >>> snapshot = TmuxSnapshot(
    ...     panes=(
    ...         PaneRef(PaneTarget("%2"), WindowTarget("@1"), SessionTarget("$0"),
    ...                 pane_index=1, active=True, title="logs"),
    ...         PaneRef(PaneTarget("%1"), WindowTarget("@1"), SessionTarget("$0"),
    ...                 pane_index=0, active=True, title="editor"),
    ...     ),
    ... )
    >>> plan = (
    ...     panes()
    ...     .filter(active=True)
    ...     .order_by("pane_index")
    ...     .commands(lambda pane: pane.cmd.resize_pane(height=20))
    ... )
    >>> plan.to_chain(snapshot).argvs()
    (('resize-pane', '-t', '%1', '-y', '20'), ('resize-pane', '-t', '%2', '-y', '20'))
    """

    node: _CommandPlanNode

    def to_chain(self, source: SnapshotSource) -> CommandChain:
        """Resolve the query and compile mapped commands (pure).

        Parameters
        ----------
        source : SnapshotSource
            A :class:`TmuxSnapshot` or a :class:`SnapshotProvider`.

        Returns
        -------
        CommandChain

        Raises
        ------
        NoCommandsResolved
            If the resolved query produced no commands.
        ChainabilityError
            If a mapped command is non-chainable -- its output would be
            consumed mid-chain (e.g. ``show-option``). Raw ``CommandCall``
            composition via ``>>`` is the explicit escape hatch and is not
            checked.
        """
        calls: list[CommandCall] = []
        for row in self.node.query.all(source):
            calls.extend(_to_calls(self.node.mapper(row)))
        if not calls:
            msg = "command plan resolved to no commands"
            raise NoCommandsResolved(msg)
        for call in calls:
            if not is_chainable(call.name):
                msg = (
                    f"command {call.name!r} is not chainable and cannot be "
                    f"folded into a one-dispatch sequence"
                )
                raise ChainabilityError(msg)
        return CommandChain(tuple(calls))

    def run(self, runner: PlanRunner) -> None:
        """Resolve, compile, and dispatch the plan in one tmux invocation.

        An empty plan is a no-op (it does not raise), mirroring libtmux's
        lenient list-accessor contract.

        Examples
        --------
        Dispatch ``send-keys`` to every active pane in one invocation, against
        a live tmux server:

        >>> from libtmux._experimental.chain import SessionPlanExecutor
        >>> plan = panes().filter(active=True).commands(
        ...     lambda pane: pane.cmd.send_keys("echo libtmux", enter=True),
        ... )
        >>> plan.run(SessionPlanExecutor(session))
        """
        try:
            sequence = self.to_chain(runner)
        except NoCommandsResolved:
            return None
        sequence.run(runner)
        return None


def panes() -> PaneQuery:
    """Start a lazy pane query.

    Examples
    --------
    >>> panes()
    PaneQuery(active_filter=None, ordering=None, limit_count=None)
    """
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
