"""Pluggable planners that decide how a lazy plan dispatches.

A planner is pure policy: given the recorded operations it returns a list of
:class:`PlanStep` units, and :meth:`~.plan.LazyPlan.execute` runs them. Swapping
planners changes *how many tmux dispatches* a plan costs without changing its
result, so strategies can be A/B-tested (same :class:`~.plan.PlanResult`,
differing dispatch count).

- :class:`SequentialPlanner` -- one dispatch per operation (the safe default).
- :class:`FoldingPlanner` -- fold maximal runs of chainable ops into one
  ``tmux a ; b`` dispatch.
- :class:`MarkedPlanner` -- additionally fold a pane creation plus the chainable
  ops that decorate it into a *single* dispatch via tmux's ``{marked}`` register
  (the chainable-commands lone-pane optimization).
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops._types import SlotRef

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.experimental.ops.operation import Operation


@dataclass(frozen=True)
class PlanStep:
    """One dispatch unit.

    A single op (``len(indices) == 1``), a ``;``-folded chain (more, ``marked``
    false), or a ``{marked}`` fold (``marked`` true: ``indices[0]`` is the pane
    creation, the rest decorate it through ``{marked}``).
    """

    indices: tuple[int, ...]
    marked: bool = False


@t.runtime_checkable
class Planner(t.Protocol):
    """Decides the dispatch units for a plan's operations."""

    def plan(self, operations: Sequence[Operation[t.Any]]) -> list[PlanStep]:
        """Return the ordered dispatch units for *operations*."""
        ...


class SequentialPlanner:
    """Dispatch each operation on its own (one tmux call per op)."""

    def plan(self, operations: Sequence[Operation[t.Any]]) -> list[PlanStep]:
        """One single-op step per operation.

        Examples
        --------
        >>> from libtmux.experimental.ops import SendKeys
        >>> from libtmux.experimental.ops._types import PaneId
        >>> SequentialPlanner().plan([SendKeys(target=PaneId("%1"), keys="a")])
        [PlanStep(indices=(0,), marked=False)]
        """
        return [PlanStep((index,)) for index in range(len(operations))]


def _fold_runs(operations: Sequence[Operation[t.Any]], start: int) -> list[PlanStep]:
    """Group maximal runs of chainable ops from *start* into chain/single steps."""
    steps: list[PlanStep] = []
    index = start
    total = len(operations)
    while index < total:
        if operations[index].chainable:
            cursor = index
            while cursor < total and operations[cursor].chainable:
                cursor += 1
            steps.append(PlanStep(tuple(range(index, cursor))))
            index = cursor
        else:
            steps.append(PlanStep((index,)))
            index += 1
    return steps


class FoldingPlanner:
    """Fold maximal runs of chainable ops into one ``;`` dispatch each."""

    def plan(self, operations: Sequence[Operation[t.Any]]) -> list[PlanStep]:
        """Chain consecutive chainable ops; dispatch the rest alone.

        Examples
        --------
        >>> from libtmux.experimental.ops import SendKeys
        >>> from libtmux.experimental.ops._types import PaneId
        >>> ops = [
        ...     SendKeys(target=PaneId("%1"), keys="a"),
        ...     SendKeys(target=PaneId("%1"), keys="b"),
        ... ]
        >>> FoldingPlanner().plan(ops)
        [PlanStep(indices=(0, 1), marked=False)]
        """
        return _fold_runs(operations, 0)


class MarkedPlanner:
    """Fold a pane creation + the chainable ops that decorate it into one call.

    When a pane-creating op (``effects.creates == "pane"``) is immediately
    followed by chainable ops that target *its* slot, they collapse into a single
    ``split-window … ; select-pane -m ; … -t {marked} … ; select-pane -M``
    dispatch. Anything else folds like :class:`FoldingPlanner`.
    """

    def plan(self, operations: Sequence[Operation[t.Any]]) -> list[PlanStep]:
        """Emit ``{marked}`` folds where possible, else fold normally.

        Examples
        --------
        >>> from libtmux.experimental.ops import SplitWindow, SendKeys
        >>> from libtmux.experimental.ops._types import SlotRef, WindowId
        >>> ops = [
        ...     SplitWindow(target=WindowId("@1")),
        ...     SendKeys(target=SlotRef(0), keys="vim", enter=True),
        ... ]
        >>> MarkedPlanner().plan(ops)
        [PlanStep(indices=(0, 1), marked=True)]
        """
        steps: list[PlanStep] = []
        index = 0
        total = len(operations)
        while index < total:
            decorates = _marked_decorates(operations, index)
            if decorates:
                steps.append(PlanStep((index, *decorates), marked=True))
                index = decorates[-1] + 1
            else:
                run = _fold_runs(operations, index)[0]
                steps.append(run)
                index = run.indices[-1] + 1
        return steps


def _split_at_boundaries(
    step: PlanStep,
    boundaries: frozenset[int],
) -> list[PlanStep]:
    """Break *step* wherever a boundary falls between two of its indices.

    A boundary at index ``i`` means a host step runs after op ``i``, so no fold
    may span ``i -> i+1``. Splitting only ever breaks a step into contiguous
    sub-runs (never merges), so it cannot change the result -- only the dispatch
    grouping. A ``marked`` step keeps ``marked=True`` on its first sub-run iff the
    creator still keeps at least one decorate; later sub-runs become plain
    ``;``-chains that resolve the creator's now-bound id instead of ``{marked}``.
    """
    indices = step.indices
    cuts = [k + 1 for k in range(len(indices) - 1) if indices[k] in boundaries]
    if not cuts:
        return [step]
    starts, ends = [0, *cuts], [*cuts, len(indices)]
    runs = [indices[lo:hi] for lo, hi in zip(starts, ends, strict=True)]
    return [
        PlanStep(run, marked=step.marked and pos == 0 and len(run) > 1)
        for pos, run in enumerate(runs)
    ]


@dataclass(frozen=True)
class BoundedPlanner:
    """Wrap a planner so no fold crosses a host-step boundary.

    *boundaries* are operation indices after which a host step runs (for the
    workspace runner, exactly ``frozenset(compiled.host_after)``). The *inner*
    planner runs over the full operation list -- so its global
    :class:`~._types.SlotRef` matching is unaffected -- and every resulting
    :class:`PlanStep` is then split at any boundary it spans.
    """

    inner: Planner
    boundaries: frozenset[int]

    def plan(self, operations: Sequence[Operation[t.Any]]) -> list[PlanStep]:
        """Plan with *inner*, then split each step at host-step boundaries.

        Examples
        --------
        >>> from libtmux.experimental.ops import SendKeys
        >>> from libtmux.experimental.ops._types import PaneId
        >>> ops = [
        ...     SendKeys(target=PaneId("%1"), keys="a"),
        ...     SendKeys(target=PaneId("%1"), keys="b"),
        ... ]
        >>> BoundedPlanner(FoldingPlanner(), frozenset({0})).plan(ops)
        [PlanStep(indices=(0,), marked=False), PlanStep(indices=(1,), marked=False)]
        >>> BoundedPlanner(FoldingPlanner(), frozenset()).plan(ops)
        [PlanStep(indices=(0, 1), marked=False)]
        """
        steps: list[PlanStep] = []
        for step in self.inner.plan(operations):
            steps.extend(_split_at_boundaries(step, self.boundaries))
        return steps


def _marked_decorates(
    operations: Sequence[Operation[t.Any]],
    index: int,
) -> tuple[int, ...]:
    """Return the indices of chainable ops decorating a pane created at *index*.

    Empty unless *index* is a pane creation followed by at least one chainable op
    whose target is that creation's :class:`SlotRef`.
    """
    creator = operations[index]
    if creator.effects.creates != "pane" or creator.chainable:
        return ()
    decorates: list[int] = []
    cursor = index + 1
    while cursor < len(operations):
        op = operations[cursor]
        if op.chainable and op.target == SlotRef(index):
            decorates.append(cursor)
            cursor += 1
        else:
            break
    return tuple(decorates)
