"""Core engine abstractions: requests, results, and the engine protocols.

Adapted from the ``libtmux-protocol-engines`` prototype. A
:class:`CommandRequest` is a rendered tmux argv plus an optional binary path; a
:class:`CommandResult` is the structured outcome. :class:`TmuxEngine` and
:class:`AsyncTmuxEngine` are :class:`typing.Protocol` types, so any object with
the right methods is an engine -- including a live :class:`libtmux.Server` for
the classic case -- without inheriting a base class.
"""

from __future__ import annotations

import enum
import typing as t
from dataclasses import dataclass, field

if t.TYPE_CHECKING:
    import pathlib
    from collections.abc import Sequence


@dataclass(frozen=True)
class CommandRequest:
    """A rendered tmux command, ready for an engine to execute.

    Parameters
    ----------
    args : tuple[str, ...]
        The tmux argv *after* the binary (e.g. ``("split-window", "-t", "%1")``).
    tmux_bin : str or None
        Override the tmux binary for this request; ``None`` lets the engine
        decide.

    Examples
    --------
    >>> CommandRequest.from_args("split-window", "-t", "%1")
    CommandRequest(args=('split-window', '-t', '%1'), tmux_bin=None)
    >>> CommandRequest.from_args("kill-window", "-t", 2).args
    ('kill-window', '-t', '2')
    """

    args: tuple[str, ...]
    tmux_bin: str | None = None

    @classmethod
    def from_args(
        cls,
        *args: t.Any,
        tmux_bin: str | pathlib.Path | None = None,
    ) -> CommandRequest:
        """Build a request from arbitrary tokens, stringifying each."""
        return cls(
            args=tuple(map(str, args)),
            tmux_bin=str(tmux_bin) if tmux_bin is not None else None,
        )


@dataclass(frozen=True)
class CommandResult:
    """The structured outcome of executing a :class:`CommandRequest`.

    A tmux-side failure (``%error`` / nonzero exit) is *data* here -- it sets
    ``returncode`` and ``stderr`` rather than raising. Only engine-broken
    conditions (missing binary, lost connection, protocol desync) raise.

    Parameters
    ----------
    cmd : tuple[str, ...]
        The full argv that ran (including the tmux binary).
    stdout, stderr : tuple[str, ...]
        Captured output lines.
    returncode : int
        tmux exit code (``-1`` when unknown).
    """

    cmd: tuple[str, ...]
    stdout: tuple[str, ...] = ()
    stderr: tuple[str, ...] = ()
    returncode: int = 0


class EngineKind(str, enum.Enum):
    """Named engine families."""

    SUBPROCESS = "subprocess"
    CONCRETE = "concrete"
    CONTROL_MODE = "control_mode"
    ASYNCIO = "asyncio"
    IMSG = "imsg"


@dataclass(frozen=True)
class EngineSpec:
    """A typed, serializable selector for an engine family.

    Examples
    --------
    >>> EngineSpec.subprocess().kind
    <EngineKind.SUBPROCESS: 'subprocess'>
    >>> EngineSpec.imsg(protocol_version=8).protocol_version
    8
    >>> EngineSpec.subprocess(protocol_version=8)
    Traceback (most recent call last):
    ...
    ValueError: protocol_version is only valid for the imsg engine
    """

    kind: EngineKind
    protocol_version: int | None = None
    extra: t.Mapping[str, t.Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize and validate the spec."""
        kind = EngineKind(self.kind)
        if kind is not EngineKind.IMSG and self.protocol_version is not None:
            msg = "protocol_version is only valid for the imsg engine"
            raise ValueError(msg)
        object.__setattr__(self, "kind", kind)

    @classmethod
    def subprocess(cls, *, protocol_version: int | None = None) -> EngineSpec:
        """Build a subprocess (classic) engine spec."""
        return cls(kind=EngineKind.SUBPROCESS, protocol_version=protocol_version)

    @classmethod
    def concrete(cls) -> EngineSpec:
        """Build a concrete (in-memory) engine spec."""
        return cls(kind=EngineKind.CONCRETE)

    @classmethod
    def control_mode(cls) -> EngineSpec:
        """Build a control-mode engine spec."""
        return cls(kind=EngineKind.CONTROL_MODE)

    @classmethod
    def asyncio(cls) -> EngineSpec:
        """Build an asyncio engine spec."""
        return cls(kind=EngineKind.ASYNCIO)

    @classmethod
    def imsg(cls, *, protocol_version: int | None = None) -> EngineSpec:
        """Build an imsg (native binary) engine spec."""
        return cls(kind=EngineKind.IMSG, protocol_version=protocol_version)


@t.runtime_checkable
class TmuxEngine(t.Protocol):
    """A synchronous executor of tmux commands."""

    def run(self, request: CommandRequest) -> CommandResult:
        """Execute one tmux command and return its structured result."""
        ...

    def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Execute requests in order, returning one result per request.

        Persistent-connection engines (control mode) override this to pipeline;
        stateless engines implement it as a loop over :meth:`run`.
        """
        ...


@t.runtime_checkable
class AsyncTmuxEngine(t.Protocol):
    """An asynchronous executor of tmux commands."""

    async def run(self, request: CommandRequest) -> CommandResult:
        """Execute one tmux command and return its structured result."""
        ...

    async def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Execute requests in order, returning one result per request."""
        ...
