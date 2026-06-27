"""Exceptions for :mod:`libtmux.experimental.ops`.

All exceptions subclass :class:`libtmux.exc.LibTmuxException`, so existing
``except LibTmuxException`` handlers keep working while the operation layer
stays isolated under :mod:`libtmux.experimental`.
"""

from __future__ import annotations

import typing as t

from libtmux.exc import LibTmuxException

if t.TYPE_CHECKING:
    from collections.abc import Sequence


class OperationError(LibTmuxException):
    """Base class for problems building or registering operations."""


class UnknownOperation(OperationError):
    """No operation is registered under the requested ``kind``.

    Examples
    --------
    >>> raise UnknownOperation("split_window")
    Traceback (most recent call last):
    ...
    libtmux.experimental.ops.exc.UnknownOperation: no operation registered for
    kind 'split_window'
    """

    def __init__(self, kind: str) -> None:
        self.kind = kind
        msg = f"no operation registered for kind {kind!r}"
        super().__init__(msg)


class DuplicateOperation(OperationError):
    """An operation ``kind`` is already registered.

    Examples
    --------
    >>> raise DuplicateOperation("split_window")
    Traceback (most recent call last):
    ...
    libtmux.experimental.ops.exc.DuplicateOperation: an operation is already
    registered for kind 'split_window'
    """

    def __init__(self, kind: str) -> None:
        self.kind = kind
        msg = f"an operation is already registered for kind {kind!r}"
        super().__init__(msg)


class ForwardCaptureError(OperationError):
    """A plan step references a slot that captured no id.

    Raised when an operation targets the result of an earlier step (via a
    :class:`~._types.SlotRef`) but that step captured no id -- either it has not
    run yet (a forward or self reference), or it is not a capturing creator (a
    mutating op, or a creator built with ``capture=False``). Failing here points
    at the unbound reference rather than letting a later tmux command fail with an
    opaque target error.

    Examples
    --------
    >>> raise ForwardCaptureError(2, "self")
    Traceback (most recent call last):
    ...
    libtmux.experimental.ops.exc.ForwardCaptureError: plan step references slot 2
    (its own id) but that step captured no id; only an earlier capturing creator
    can be targeted
    """

    def __init__(self, slot: int, part: str) -> None:
        self.slot = slot
        self.part = part
        target = "its own id" if part == "self" else f"its {part!r} child"
        msg = (
            f"plan step references slot {slot} ({target}) but that step captured "
            f"no id; only an earlier capturing creator can be targeted"
        )
        super().__init__(msg)


class VersionUnsupported(OperationError):
    """An operation cannot render against the given tmux version.

    Examples
    --------
    >>> raise VersionUnsupported("split_window", need="3.0", have="2.9")
    Traceback (most recent call last):
    ...
    libtmux.experimental.ops.exc.VersionUnsupported: operation 'split_window'
    requires tmux >= 3.0 (have 2.9)
    """

    def __init__(self, kind: str, *, need: str, have: str) -> None:
        self.kind = kind
        self.need = need
        self.have = have
        msg = f"operation {kind!r} requires tmux >= {need} (have {have})"
        super().__init__(msg)


class TmuxCommandError(LibTmuxException):
    """A tmux command reported failure, raised by ``Result.raise_for_status()``.

    The constructor mirrors :class:`subprocess.CalledProcessError`'s argument
    order (``returncode``, ``cmd``, ``stdout``, ``stderr``) so the failure
    surface is familiar to anyone who has handled a subprocess error.

    Parameters
    ----------
    returncode : int
        The tmux process exit code (``-1`` when unknown, e.g. a timeout).
    cmd : Sequence[str]
        The rendered tmux argv that failed.
    stdout : Sequence[str], optional
        Captured stdout lines.
    stderr : Sequence[str], optional
        Captured stderr lines.

    Examples
    --------
    >>> raise TmuxCommandError(1, ["split-window", "-t", "%999"],
    ...     stderr=["can't find pane %999"])
    Traceback (most recent call last):
    ...
    libtmux.experimental.ops.exc.TmuxCommandError: tmux 'split-window -t %999'
    failed (exit 1): can't find pane %999
    """

    def __init__(
        self,
        returncode: int,
        cmd: Sequence[str],
        stdout: Sequence[str] | None = None,
        stderr: Sequence[str] | None = None,
    ) -> None:
        self.returncode = returncode
        self.cmd = tuple(cmd)
        self.stdout = tuple(stdout) if stdout is not None else ()
        self.stderr = tuple(stderr) if stderr is not None else ()
        detail = " ".join(self.stderr).strip()
        suffix = f": {detail}" if detail else ""
        rendered = " ".join(self.cmd)
        msg = f"tmux {rendered!r} failed (exit {returncode}){suffix}"
        super().__init__(msg)
