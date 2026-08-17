"""Pluggable planners that divide a lazy plan into execution steps.

A planner is pure policy: given the recorded operations it returns a list of
:class:`PlanStep` units, and :meth:`~.plan.LazyPlan.execute` runs them. A step is
an ordered batch of ready-to-render requests, never a tmux ``;`` command group.

- :class:`SequentialPlanner` -- one planner step per operation.
- :class:`BatchingPlanner` -- batch maximal runs of ready operations.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.experimental.ops.operation import Operation


@dataclass(frozen=True)
class PlanStep:
    """One execution unit.

    A single operation or an ordered request batch. Every index retains its
    own request and result.

    Attributes
    ----------
    indices : tuple[int, ...]
        Operation indices included in this step, in execution order.
    """

    indices: tuple[int, ...]


@t.runtime_checkable
class Planner(t.Protocol):
    """Decide the ordered execution steps for a plan's operations."""

    def plan(self, operations: Sequence[Operation[t.Any]]) -> list[PlanStep]:
        """Return the ordered planner steps for *operations*."""
        ...


class SequentialPlanner:
    """Put each operation in its own planner step."""

    def plan(self, operations: Sequence[Operation[t.Any]]) -> list[PlanStep]:
        """One single-op step per operation.

        Examples
        --------
        >>> from libtmux.experimental.ops import SendKeys
        >>> from libtmux.experimental.ops._types import PaneId
        >>> SequentialPlanner().plan([SendKeys(target=PaneId("%1"), keys="a")])
        [PlanStep(indices=(0,))]
        """
        return [PlanStep((index,)) for index in range(len(operations))]


def _batch_runs(operations: Sequence[Operation[t.Any]], start: int) -> list[PlanStep]:
    """Group maximal batchable runs from *start* into execution steps."""
    steps: list[PlanStep] = []
    index = start
    total = len(operations)
    while index < total:
        if operations[index].batchable and operations[index].primitive:
            cursor = index
            while (
                cursor < total
                and operations[cursor].batchable
                and operations[cursor].primitive
            ):
                cursor += 1
            steps.append(PlanStep(tuple(range(index, cursor))))
            index = cursor
        else:
            steps.append(PlanStep((index,)))
            index += 1
    return steps


class BatchingPlanner:
    """Batch maximal runs of ready-to-render primitive operations."""

    def plan(self, operations: Sequence[Operation[t.Any]]) -> list[PlanStep]:
        """Batch consecutive batchable ops; put the rest in single-op steps.

        Examples
        --------
        >>> from libtmux.experimental.ops import SendKeys
        >>> from libtmux.experimental.ops._types import PaneId
        >>> ops = [
        ...     SendKeys(target=PaneId("%1"), keys="a"),
        ...     SendKeys(target=PaneId("%1"), keys="b"),
        ... ]
        >>> BatchingPlanner().plan(ops)
        [PlanStep(indices=(0, 1))]
        """
        return _batch_runs(operations, 0)


def _split_at_boundaries(
    step: PlanStep,
    boundaries: frozenset[int],
) -> list[PlanStep]:
    """Break *step* wherever a boundary falls between two of its indices.

    A boundary at index ``i`` means a host step runs after op ``i``, so no batch
    may span ``i -> i+1``. Splitting only ever breaks a step into contiguous
    sub-runs (never merges), so it cannot change the result -- only planner-step
    grouping.
    """
    indices = step.indices
    cuts = [k + 1 for k in range(len(indices) - 1) if indices[k] in boundaries]
    if not cuts:
        return [step]
    starts, ends = [0, *cuts], [*cuts, len(indices)]
    runs = [indices[lo:hi] for lo, hi in zip(starts, ends, strict=True)]
    return [PlanStep(run) for run in runs]


@dataclass(frozen=True)
class BoundedPlanner:
    """Wrap a planner so no batch crosses a host-step boundary.

    *boundaries* are operation indices after which a host step runs (for the
    workspace runner, exactly ``frozenset(compiled.host_after)``). The *inner*
    planner runs over the full operation list -- so its global
    :class:`~._types.SlotRef` matching is unaffected -- and every resulting
    :class:`PlanStep` is then split at any boundary it spans.

    Attributes
    ----------
    inner : Planner
        Planner whose execution steps are constrained.
    boundaries : frozenset[int]
        Operation indices after which a host-side step must run.
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
        >>> BoundedPlanner(BatchingPlanner(), frozenset({0})).plan(ops)
        [PlanStep(indices=(0,)), PlanStep(indices=(1,))]
        >>> BoundedPlanner(BatchingPlanner(), frozenset()).plan(ops)
        [PlanStep(indices=(0, 1))]
        """
        steps: list[PlanStep] = []
        for step in self.inner.plan(operations):
            steps.extend(_split_at_boundaries(step, self.boundaries))
        return steps
