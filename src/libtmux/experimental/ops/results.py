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

from libtmux.experimental.models.snapshots import (
    ClientSnapshot,
    PaneSnapshot,
    ServerSnapshot,
    SessionSnapshot,
    WindowSnapshot,
)
from libtmux.experimental.ops.exc import TmuxCommandError

if t.TYPE_CHECKING:
    from collections.abc import Mapping

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

    @property
    def created_id(self) -> str | None:
        """The id of an object this operation created, if any (else ``None``).

        Result subclasses for creation ops override this; a lazy plan reads it to
        bind a forward :class:`~._types.SlotRef`. The base result creates nothing.
        """
        return None

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
class AckResult(Result):
    """Result of an operation that returns no data -- only success or failure.

    Many tmux commands (``rename-window``, ``kill-pane``, ``select-window``, ...)
    print nothing. In the CLI they exit ``0`` on success or write to stderr and
    exit nonzero on failure; in control mode tmux frames them as ``%end``
    (success) or ``%error`` (failure) -- it never calls ``cmdq_print`` for them
    (see tmux ``cmd-queue.c``). An :class:`AckResult` is the typed
    acknowledgement for exactly that case: no payload, but
    :meth:`~Result.raise_for_status` still surfaces the error path, because a
    no-output command can still fail.

    Examples
    --------
    >>> from libtmux.experimental.ops import RenameWindow
    >>> from libtmux.experimental.ops._types import WindowId
    >>> op = RenameWindow(target=WindowId("@1"), name="build")
    >>> ok = op.build_result(returncode=0)
    >>> type(ok).__name__, ok.ok
    ('AckResult', True)
    >>> failed = op.build_result(returncode=1, stderr=("can't find window @1",))
    >>> failed.ok
    False
    """


@dataclass(frozen=True)
class SplitWindowResult(Result):
    """Result of a ``split-window`` operation.

    Adds the id of the pane tmux created, when it was captured.
    """

    new_pane_id: str | None = None

    @property
    def created_id(self) -> str | None:
        """The new pane's id."""
        return self.new_pane_id


@dataclass(frozen=True)
class CreateResult(Result):
    """Result of an operation that creates an object and captures its id.

    Shared by ``new-window`` / ``new-session`` (and other ``-P -F``-capturing
    creators); :attr:`new_id` holds the created object's id (``@N``/``$N``).
    """

    new_id: str | None = None

    @property
    def created_id(self) -> str | None:
        """The created object's id."""
        return self.new_id


@dataclass(frozen=True)
class CapturePaneResult(Result):
    """Result of a ``capture-pane`` operation.

    Adds the captured pane lines as :attr:`lines` (also available as
    :attr:`stdout`).
    """

    lines: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ListPanesResult(Result):
    """Result of a ``list-panes`` operation.

    Stores the parsed per-pane format mappings as JSON-friendly :attr:`rows`
    (so the result serializes without snapshot objects), and derives typed
    :class:`~..models.snapshots.PaneSnapshot` / :class:`ServerSnapshot` views on
    demand.
    """

    rows: tuple[Mapping[str, str], ...] = ()

    @property
    def panes(self) -> tuple[PaneSnapshot, ...]:
        """One typed pane snapshot per row."""
        return tuple(PaneSnapshot.from_format(row) for row in self.rows)

    @property
    def server(self) -> ServerSnapshot:
        """The full session/window/pane tree built from the rows."""
        return ServerSnapshot.from_pane_rows(self.rows)


@dataclass(frozen=True)
class ListWindowsResult(Result):
    """Result of a ``list-windows`` operation (typed :attr:`windows`)."""

    rows: tuple[Mapping[str, str], ...] = ()

    @property
    def windows(self) -> tuple[WindowSnapshot, ...]:
        """One typed window snapshot per row."""
        return tuple(WindowSnapshot.from_format(row) for row in self.rows)


@dataclass(frozen=True)
class ListSessionsResult(Result):
    """Result of a ``list-sessions`` operation (typed :attr:`sessions`)."""

    rows: tuple[Mapping[str, str], ...] = ()

    @property
    def sessions(self) -> tuple[SessionSnapshot, ...]:
        """One typed session snapshot per row."""
        return tuple(SessionSnapshot.from_format(row) for row in self.rows)


@dataclass(frozen=True)
class ListClientsResult(Result):
    """Result of a ``list-clients`` operation (typed :attr:`clients`)."""

    rows: tuple[Mapping[str, str], ...] = ()

    @property
    def clients(self) -> tuple[ClientSnapshot, ...]:
        """One typed client snapshot per row."""
        return tuple(ClientSnapshot.from_format(row) for row in self.rows)


@dataclass(frozen=True)
class HasSessionResult(Result):
    """Result of a ``has-session`` existence query.

    ``has-session`` exits ``0`` when the session exists and nonzero otherwise --
    a valid answer, not a failure -- so this result is always ``complete`` and
    carries the answer in :attr:`exists`.
    """

    exists: bool = False


@dataclass(frozen=True)
class DisplayMessageResult(Result):
    """Result of ``display-message -p``: the formatted :attr:`text`."""

    text: str = ""


@dataclass(frozen=True)
class ShowOptionsResult(Result):
    """Result of ``show-options``: parsed ``name value`` pairs in :attr:`options`."""

    options: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ShowBufferResult(Result):
    """Result of ``show-buffer``: the buffer contents as :attr:`text`."""

    text: str = ""
