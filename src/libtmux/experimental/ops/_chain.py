r"""Chaining and ``;``-folding for lazy plans.

A run of *chainable* operations can render to a single ``tmux a \; b`` invocation
and dispatch once, instead of one process fork / control-mode command per
operation. Only operations whose ``chainable`` class var is ``True`` (no
captured output, no created object) fold; the rest dispatch alone.

tmux runs a ``;`` sequence up to the first error and drops the remainder
(``cmd-queue.c`` ``cmdq_remove_group``), returning one merged stdout/exit with no
per-command boundary. :func:`attribute` recovers a typed result per operation:
on success every member is ``complete``; on failure the first member is
``failed`` and the rest are ``skipped`` (the status the spine reserves for
exactly this case).

Because that merged stdout has no per-command boundary, folding an op that
*captures* output (or creates an object whose id it prints) would silently
mis-attribute those lines. :func:`ensure_chainable` is the fail-closed guard for
that, and every rendering path that emits a ``;`` fold runs it over the ops it is
about to fold -- so the mistake raises here instead of corrupting a result.
"""

from __future__ import annotations

import dataclasses
import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops._types import PaneId, Special
from libtmux.experimental.ops.exc import OperationError
from libtmux.experimental.ops.results import status_for

if t.TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from libtmux.experimental.engines.base import CommandResult
    from libtmux.experimental.ops.operation import Operation
    from libtmux.experimental.ops.results import Result


def ensure_chainable(op: Operation[t.Any]) -> None:
    """Raise if *op* cannot be folded into a ``;`` chain (fail closed).

    Examples
    --------
    >>> from libtmux.experimental.ops import CapturePane
    >>> from libtmux.experimental.ops._types import PaneId
    >>> ensure_chainable(CapturePane(target=PaneId("%1")))
    Traceback (most recent call last):
    ...
    libtmux.experimental.ops.exc.OperationError: operation 'capture_pane' is not
    chainable; it produces output or creates an object and must dispatch on its own
    """
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

    Every op is checked against :func:`ensure_chainable` first: a capturing or
    creating op has nowhere to put its stdout in a merged chain result, so it
    fails closed instead of folding.

    >>> from libtmux.experimental.ops import CapturePane, SendKeys
    >>> render_chain([
    ...     SendKeys(target=PaneId("%1"), keys="vim"),
    ...     CapturePane(target=PaneId("%1")),
    ... ])
    Traceback (most recent call last):
    ...
    libtmux.experimental.ops.exc.OperationError: operation 'capture_pane' is not
    chainable; it produces output or creates an object and must dispatch on its own
    """
    out: list[str] = []
    for index, op in enumerate(ops):
        ensure_chainable(op)
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
    if status_for(merged.returncode, merged.stderr) == "complete":
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


def render_marked(
    create: Operation[t.Any],
    decorates: Sequence[Operation[t.Any]],
    version: str | None = None,
) -> tuple[str, ...]:
    r"""Render a pane creation + its decorates as one ``{marked}`` invocation.

    Emits ``<create -P -F '#{pane_id}'> ; select-pane -m ; <decorate -t {marked}>
    ... ; select-pane -M``: the new pane is marked, every decorate addresses it
    through tmux's ``{marked}`` register, and the mark is cleared at the end.

    The *create* is the one non-chainable op the fold tolerates -- its captured id
    is the whole point, and :func:`attribute_marked` reads it back from
    ``stdout[0]``. That is exactly why every *decorate* must be chainable: a
    capturing decorate would interleave its lines into the same merged stdout and
    the captured id would be read from the wrong line. :func:`ensure_chainable`
    fails that closed.
    """
    parts: list[tuple[str, ...]] = [
        create.render(version=version),
        ("select-pane", "-m"),
    ]
    for op in decorates:
        ensure_chainable(op)
    parts.extend(
        dataclasses.replace(op, target=Special("{marked}")).render(version=version)
        for op in decorates
    )
    parts.append(("select-pane", "-M"))
    out: list[str] = []
    for index, part in enumerate(parts):
        if index:
            out.append(";")
        out.extend(_escape_arg(token) for token in part)
    return tuple(out)


def attribute_marked(
    create: Operation[t.Any],
    decorates: Sequence[Operation[t.Any]],
    merged: CommandResult,
    version: str | None = None,
) -> tuple[Result, list[Result], str | None]:
    """Split a ``{marked}`` dispatch result into the create's + decorates' results."""
    new_id = (merged.stdout[0].strip() if merged.stdout else "") or None
    # Attribute over the {marked}-retargeted decorates -- their original SlotRef
    # target is unresolved and cannot render.
    marked = [dataclasses.replace(op, target=Special("{marked}")) for op in decorates]
    if new_id is None:
        if status_for(merged.returncode, merged.stderr) == "complete":
            # A non-capturing creator (capture=False) succeeded but emitted no
            # id; every command in the fold ran.
            create_result = create.build_result(returncode=0, version=version)
            decorated = [
                op.result_with_status("complete", version=version) for op in marked
            ]
            return create_result, decorated, None
        # The create step failed: tmux stopped, so no decorate ran -- skip them
        # all rather than blaming the first.
        create_result = create.build_result(
            returncode=merged.returncode or 1,
            stderr=tuple(merged.stderr),
            version=version,
        )
        decorated = [op.result_with_status("skipped", version=version) for op in marked]
        return create_result, decorated, None
    create_result = create.build_result(returncode=0, stdout=(new_id,), version=version)
    # Attribute over decorates retargeted to the concrete new pane (not
    # ``{marked}``) so each result's operation serializes and replays to the real
    # pane; drop the create's captured id from stdout so a failed decorate is not
    # credited with it.
    resolved = [dataclasses.replace(op, target=PaneId(new_id)) for op in decorates]
    decorated = attribute(resolved, dataclasses.replace(merged, stdout=()), version)
    return create_result, decorated, new_id


@dataclass(frozen=True)
class OpChain:
    """An ordered group of operations composed with :meth:`~.Operation.then`.

    A power-user, inspectable handle for explicit chaining. Add it to a
    :class:`~.plan.LazyPlan` with :meth:`~.plan.LazyPlan.add_chain`; a folding
    planner (``execute(planner=FoldingPlanner())``) batches chainable runs anyway.

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
