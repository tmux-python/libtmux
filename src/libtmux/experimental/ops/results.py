"""Typed result values for :mod:`libtmux.experimental.ops`.

A :class:`Result` is the uniform shape every engine returns for the same
operation: the operation that produced it, the rendered argv, an execution
:data:`~libtmux.experimental.ops._types.Status`, and the captured tmux output.
Specialized payloads (a new pane id, captured lines) live on subclasses defined
next to their operations.

Results never raise on construction. Raising is opt-in via
:meth:`Result.raise_for_status`, mirroring
:meth:`subprocess.CompletedProcess.check_returncode`. *How* an engine treats a
failed result is the engine's policy: the classic engine raises in its facade to
match today's behavior, while newer engines hand the result back and let the
caller decide.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field

from libtmux.experimental.ops.exc import TmuxCommandError

if t.TYPE_CHECKING:
    from typing_extensions import Self

    from libtmux.experimental.ops._types import Status
    from libtmux.experimental.ops.operation import Operation


def status_for(returncode: int, stderr: t.Sequence[str]) -> Status:
    """Derive a result :data:`~._types.Status` from a tmux outcome.

    tmux frequently reports a failure as stderr text while still exiting ``0``,
    so non-empty stderr counts as a failure here -- a deliberate divergence from
    a returncode-only test (see :meth:`Result.raise_for_status`).

    Parameters
    ----------
    returncode : int
        The tmux process exit code.
    stderr : Sequence[str]
        Captured stderr lines.

    Returns
    -------
    Status

    Examples
    --------
    >>> status_for(0, [])
    'complete'
    >>> status_for(1, [])
    'failed'
    >>> status_for(0, ["no current session"])
    'failed'
    """
    if returncode == 0 and not stderr:
        return "complete"
    return "failed"


@dataclass(frozen=True)
class Result:
    """Base result for an executed (or simulated) operation.

    Parameters
    ----------
    operation : Operation
        The operation this result came from.
    argv : tuple[str, ...]
        The rendered tmux argv that produced this result.
    status : Status
        Execution status.
    returncode : int
        tmux exit code (``-1`` when unknown, e.g. a timeout).
    stdout, stderr : tuple[str, ...]
        Captured output lines.

    Examples
    --------
    >>> from libtmux.experimental.ops import SendKeys
    >>> from libtmux.experimental.ops._types import PaneId
    >>> result = SendKeys(target=PaneId("%1"), keys="echo hi").build_result(
    ...     argv=("send-keys", "-t", "%1", "echo hi"),
    ...     returncode=0,
    ... )
    >>> result.ok
    True
    >>> result.raise_for_status() is result
    True

    A failed result raises only when asked:

    >>> failed = SendKeys(target=PaneId("%9"), keys="x").build_result(
    ...     argv=("send-keys", "-t", "%9", "x"),
    ...     returncode=1,
    ...     stderr=("can't find pane %9",),
    ... )
    >>> failed.ok
    False
    >>> failed.raise_for_status()
    Traceback (most recent call last):
    ...
    libtmux.experimental.ops.exc.TmuxCommandError: tmux 'send-keys -t %9 x'
    failed (exit 1): can't find pane %9
    """

    operation: Operation[t.Any]
    argv: tuple[str, ...]
    status: Status
    returncode: int
    stdout: tuple[str, ...] = ()
    stderr: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """Whether the operation completed successfully."""
        return self.status == "complete"

    @property
    def failed(self) -> bool:
        """Whether the operation ran and tmux reported failure."""
        return self.status == "failed"

    def raise_for_status(self) -> Self:
        """Raise :class:`~.exc.TmuxCommandError` if the result is not OK.

        Returns ``self`` on success so it can be used fluently
        (``result = run(op, engine).raise_for_status()``). A ``failed`` or
        ``unknown`` status raises; ``complete`` and ``skipped`` do not.

        Returns
        -------
        Self

        Raises
        ------
        ~libtmux.experimental.ops.exc.TmuxCommandError
            When :attr:`status` is ``failed`` or ``unknown``.
        """
        if self.status in {"failed", "unknown"}:
            raise TmuxCommandError(
                self.returncode,
                self.argv,
                self.stdout,
                self.stderr,
            )
        return self


@dataclass(frozen=True)
class SplitWindowResult(Result):
    """Result of a ``split-window`` operation.

    Adds the id of the pane tmux created, when it was captured.
    """

    new_pane_id: str | None = None


@dataclass(frozen=True)
class CapturePaneResult(Result):
    """Result of a ``capture-pane`` operation.

    Adds the captured pane lines as :attr:`lines` (also available as
    :attr:`stdout`).
    """

    lines: tuple[str, ...] = field(default_factory=tuple)
