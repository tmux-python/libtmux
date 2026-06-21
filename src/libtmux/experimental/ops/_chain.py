r"""Chaining and ``;``-folding for lazy plans.

A run of *chainable* operations can render to a single ``tmux a \; b`` invocation
and dispatch once, instead of one process fork / control-mode command per
operation. This ports the chainable-commands prototype's fold onto the typed-op
model: only operations whose ``chainable`` class var is ``True`` (no captured
output, no created object) fold; the rest dispatch alone.

tmux runs a ``;`` sequence up to the first error and drops the remainder
(``cmd-queue.c`` ``cmdq_remove_group``), returning one merged stdout/exit with no
per-command boundary. :func:`attribute` recovers a typed result per operation:
on success every member is ``complete``; on failure the first member is
``failed`` and the rest are ``skipped`` (the status the spine reserves for
exactly this case).
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops.exc import OperationError

if t.TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from libtmux.experimental.engines.base import CommandResult
    from libtmux.experimental.ops.operation import Operation
    from libtmux.experimental.ops.results import Result


def ensure_chainable(op: Operation[t.Any]) -> None:
    """Raise if *op* cannot be folded into a ``;`` chain (fail closed)."""
    if not op.chainable:
        msg = (
            f"operation {op.kind!r} is not chainable; it produces output or "
            f"creates an object and must dispatch on its own"
        )
        raise OperationError(msg)


def _escape_arg(token: str) -> str:
    r"""Escape a trailing ``;`` so tmux does not read the arg as a separator."""
    if token.endswith(";"):
        return token[:-1] + "\\;"
    return token


def render_chain(
    ops: Sequence[Operation[t.Any]],
    version: str | None = None,
) -> tuple[str, ...]:
    r"""Render chainable ops to one argv with standalone ``;`` separators.

    Examples
    --------
    >>> from libtmux.experimental.ops import SendKeys, RenameWindow
    >>> from libtmux.experimental.ops._types import PaneId, WindowId
    >>> render_chain([
    ...     SendKeys(target=PaneId("%1"), keys="vim", enter=True),
    ...     RenameWindow(target=WindowId("@1"), name="edit"),
    ... ])
    ('send-keys', '-t', '%1', 'vim', 'Enter', ';', 'rename-window', '-t', '@1', 'edit')
    """
    out: list[str] = []
    for index, op in enumerate(ops):
        if index:
            out.append(";")
        out.extend(_escape_arg(token) for token in op.render(version=version))
    return tuple(out)


def attribute(
    ops: Sequence[Operation[t.Any]],
    merged: CommandResult,
    version: str | None = None,
) -> list[Result]:
    """Split one merged ``;``-chain result into a typed result per operation."""
    if merged.returncode == 0 and not merged.stderr:
        return [op.result_with_status("complete", version=version) for op in ops]
    first, *rest = ops
    results: list[Result] = [
        first.result_with_status(
            "failed",
            version=version,
            returncode=merged.returncode,
            stdout=tuple(merged.stdout),
            stderr=tuple(merged.stderr),
        ),
    ]
    results.extend(op.result_with_status("skipped", version=version) for op in rest)
    return results


@dataclass(frozen=True)
class OpChain:
    """An ordered group of operations composed with :meth:`~.Operation.then`.

    A power-user, inspectable handle for explicit chaining. Add it to a
    :class:`~.plan.LazyPlan` with :meth:`~.plan.LazyPlan.add_chain`; the plan's
    folded execution (``execute(fold=True)``) batches chainable runs anyway.

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
