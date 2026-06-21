"""Lazy, deferred-resolution plans over the typed operation spine.

A :class:`LazyPlan` records operations without touching tmux, so a plan can be
inspected, serialized, and executed later. Operations may target the *result of
an earlier operation* via a :class:`~._types.SlotRef` (e.g. send keys to the pane
a split is about to create); the plan resolves those references from captured ids
at execution time.

Resolution is a sans-I/O generator -- the same yield-operation / resume-with-
result trampoline the chainable-commands prototype uses. The sync
:meth:`LazyPlan.execute` and async :meth:`LazyPlan.aexecute` drivers differ only
in ``run(...)`` versus ``await arun(...)``; the resolution logic is written once.
"""

from __future__ import annotations

import dataclasses
import typing as t
from dataclasses import dataclass, field

from libtmux.experimental.engines.base import CommandRequest
from libtmux.experimental.ops._chain import attribute, render_chain
from libtmux.experimental.ops._types import (
    PaneId,
    SessionId,
    SlotRef,
    Special,
    WindowId,
)
from libtmux.experimental.ops.exc import OperationError
from libtmux.experimental.ops.execute import arun, run
from libtmux.experimental.ops.serialize import operation_from_dict, operation_to_dict

if t.TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    from typing_extensions import Self

    from libtmux.experimental.engines.base import (
        AsyncTmuxEngine,
        CommandResult,
        TmuxEngine,
    )
    from libtmux.experimental.ops._chain import OpChain
    from libtmux.experimental.ops._types import Target
    from libtmux.experimental.ops.operation import Operation
    from libtmux.experimental.ops.results import Result


@dataclass(frozen=True)
class _Single:
    """Drive request: run one resolved operation and return its typed result."""

    op: Operation[t.Any]


@dataclass(frozen=True)
class _Chain:
    """Drive request: dispatch a folded ``;`` chain and return the merged result."""

    argv: tuple[str, ...]


def _target_from_id(value: str) -> Target:
    """Map a captured concrete id back to its typed target."""
    if value.startswith("%"):
        return PaneId(value)
    if value.startswith("@"):
        return WindowId(value)
    if value.startswith("$"):
        return SessionId(value)
    return Special(value)


def _resolve(
    operation: Operation[t.Any],
    bindings: dict[int, str],
) -> Operation[t.Any]:
    """Substitute a :class:`SlotRef` target with a captured concrete id."""
    target = operation.target
    if not isinstance(target, SlotRef):
        return operation
    try:
        concrete = bindings[target.slot] + target.suffix
    except KeyError as error:
        msg = (
            f"slot {target.slot} has no captured id yet; a plan step can only "
            f"target an earlier step that creates an object"
        )
        raise OperationError(msg) from error
    return dataclasses.replace(operation, target=_target_from_id(concrete))


@dataclass(frozen=True)
class PlanResult:
    """The outcome of executing a :class:`LazyPlan`.

    Parameters
    ----------
    results : tuple[Result, ...]
        One result per recorded operation, in order.
    bindings : dict[int, str]
        Maps a creating step's index to the concrete id it produced.
    """

    results: tuple[Result, ...]
    bindings: dict[int, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Whether every step completed successfully."""
        return all(result.ok for result in self.results)

    def raise_for_status(self) -> Self:
        """Raise on the first failed step; return ``self`` when all are OK."""
        for result in self.results:
            result.raise_for_status()
        return self


class LazyPlan:
    """Record operations now; resolve refs and execute them later.

    Examples
    --------
    Build a plan that splits a window then types into the *new* pane, and run it
    against the in-memory concrete engine (no tmux required):

    >>> from libtmux.experimental.ops import SplitWindow, SendKeys
    >>> from libtmux.experimental.ops._types import WindowId
    >>> from libtmux.experimental.engines import ConcreteEngine
    >>> plan = LazyPlan()
    >>> pane = plan.add(SplitWindow(target=WindowId("@1")))
    >>> _ = plan.add(SendKeys(target=pane, keys="vim", enter=True))
    >>> outcome = plan.execute(ConcreteEngine())
    >>> outcome.bindings
    {0: '%1'}
    >>> outcome.results[1].argv
    ('send-keys', '-t', '%1', 'vim', 'Enter')
    """

    def __init__(self) -> None:
        self._operations: list[Operation[t.Any]] = []

    def add(self, operation: Operation[t.Any]) -> SlotRef:
        """Record an operation; return a :class:`SlotRef` to its eventual id.

        The returned ref can be used as the ``target`` of a later operation to
        address the object this one creates.
        """
        self._operations.append(operation)
        return SlotRef(len(self._operations) - 1)

    @property
    def operations(self) -> tuple[Operation[t.Any], ...]:
        """The recorded operations, in order."""
        return tuple(self._operations)

    def __len__(self) -> int:
        """Return the number of recorded operations."""
        return len(self._operations)

    def __iter__(self) -> Iterator[Operation[t.Any]]:
        """Iterate recorded operations in order."""
        return iter(self._operations)

    def to_list(self) -> list[dict[str, t.Any]]:
        """Serialize the whole plan to a list of plain operation dicts."""
        return [operation_to_dict(operation) for operation in self._operations]

    @classmethod
    def from_list(cls, data: t.Sequence[t.Mapping[str, t.Any]]) -> LazyPlan:
        """Reconstruct a plan from :meth:`to_list` output."""
        plan = cls()
        plan._operations = [operation_from_dict(item) for item in data]
        return plan

    def add_chain(self, chain: OpChain) -> None:
        """Record every operation of an :class:`~._chain.OpChain` in order."""
        self._operations.extend(chain.ops)

    def _drive(
        self,
        version: str | None,
        fold: bool,
    ) -> Generator[_Single | _Chain, t.Any, PlanResult]:
        """Sans-I/O resolution core.

        Yields a :class:`_Single` (driver runs one op and returns its
        :class:`~.results.Result`) or, when ``fold`` is set, a :class:`_Chain`
        for a maximal run of chainable ops (driver returns the merged
        :class:`~..engines.base.CommandResult`, attributed per op here). The
        sync and async drivers differ only in ``run`` vs ``await arun`` and
        ``engine.run`` vs ``await engine.run``.
        """
        bindings: dict[int, str] = {}
        results: dict[int, Result] = {}
        index = 0
        total = len(self._operations)
        while index < total:
            operation = self._operations[index]
            if fold and operation.chainable:
                indices: list[int] = []
                group: list[Operation[t.Any]] = []
                cursor = index
                while cursor < total and self._operations[cursor].chainable:
                    indices.append(cursor)
                    group.append(_resolve(self._operations[cursor], bindings))
                    cursor += 1
                if len(group) == 1:
                    results[indices[0]] = yield _Single(group[0])
                else:
                    merged: CommandResult = yield _Chain(render_chain(group, version))
                    results.update(
                        zip(indices, attribute(group, merged, version), strict=True),
                    )
                index = cursor
            else:
                result = yield _Single(_resolve(operation, bindings))
                results[index] = result
                if result.created_id is not None:
                    bindings[index] = result.created_id
                index += 1
        ordered = tuple(results[slot] for slot in range(total))
        return PlanResult(ordered, bindings)

    def execute(
        self,
        engine: TmuxEngine,
        *,
        version: str | None = None,
        fold: bool = False,
    ) -> PlanResult:
        """Resolve and execute the plan synchronously.

        With ``fold=True``, maximal runs of chainable operations dispatch as one
        ``tmux a ; b`` invocation (fewer forks / one control-mode command),
        attributing a typed result per operation. ``fold`` defaults off because
        folding changes observable semantics (fewer dispatches; a folded
        failure marks the first member failed and the rest skipped).
        """
        gen = self._drive(version, fold)
        try:
            request = next(gen)
            while True:
                request = gen.send(self._dispatch(request, engine, version))
        except StopIteration as stop:
            return t.cast("PlanResult", stop.value)

    def _dispatch(
        self,
        request: _Single | _Chain,
        engine: TmuxEngine,
        version: str | None,
    ) -> t.Any:
        """Run one drive request synchronously."""
        if isinstance(request, _Chain):
            return engine.run(CommandRequest.from_args(*request.argv))
        return run(request.op, engine, version=version)

    async def aexecute(
        self,
        engine: AsyncTmuxEngine,
        *,
        version: str | None = None,
        fold: bool = False,
    ) -> PlanResult:
        """Resolve and execute the plan asynchronously (same resolution core)."""
        gen = self._drive(version, fold)
        try:
            request = next(gen)
            while True:
                if isinstance(request, _Chain):
                    raw = await engine.run(CommandRequest.from_args(*request.argv))
                    request = gen.send(raw)
                else:
                    request = gen.send(await arun(request.op, engine, version=version))
        except StopIteration as stop:
            return t.cast("PlanResult", stop.value)
