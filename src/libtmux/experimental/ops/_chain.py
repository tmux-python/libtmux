"""Ordered operation composition for lazy plans."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

if t.TYPE_CHECKING:
    from collections.abc import Iterator

    from libtmux.experimental.ops.operation import Operation


@dataclass(frozen=True)
class OpChain:
    """An ordered group of operations composed with :meth:`~.Operation.then`.

    A power-user, inspectable handle for fluent composition. Add it to a
    :class:`~.plan.LazyPlan` with :meth:`~.plan.LazyPlan.add_chain`. Composition
    records order; the selected planner decides safe request batches.

    Attributes
    ----------
    ops : tuple[Operation, ...]
        Operations in execution order.

    Examples
    --------
    >>> from libtmux.experimental.ops import SendKeys, RenameWindow
    >>> from libtmux.experimental.ops._types import PaneId, WindowId
    >>> chain = (
    ...     SendKeys(target=PaneId("%1"), keys="q")
    ...     >> RenameWindow(target=WindowId("@1"), name="done")
    ... )
    >>> [op.kind for op in chain]
    ['send_keys', 'rename_window']
    """

    ops: tuple[Operation[t.Any], ...]

    def then(self, other: Operation[t.Any] | OpChain) -> OpChain:
        """Append an operation or chain."""
        return OpChain((*self.ops, *_as_ops(other)))

    def __rshift__(self, other: Operation[t.Any] | OpChain) -> OpChain:
        """Append with ``>>``."""
        return self.then(other)

    def __iter__(self) -> Iterator[Operation[t.Any]]:
        """Iterate the operations in order."""
        return iter(self.ops)

    def __len__(self) -> int:
        """Return the number of operations in the chain."""
        return len(self.ops)


def _as_ops(other: Operation[t.Any] | OpChain) -> tuple[Operation[t.Any], ...]:
    """Normalize an operation or chain to a tuple of operations."""
    if isinstance(other, OpChain):
        return other.ops
    return (other,)
