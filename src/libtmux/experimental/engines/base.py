"""Core engine abstractions: requests, results, and the engine protocols.

A :class:`CommandRequest` is a rendered tmux argv plus an optional binary path; a
:class:`CommandResult` is the structured outcome. :class:`TmuxEngine` and
:class:`AsyncTmuxEngine` are :class:`typing.Protocol` types, so any object with
the right methods is an engine -- including a live :class:`libtmux.Server` for
the classic case -- without inheriting a base class.
"""

from __future__ import annotations

import enum
import re
import shlex
import typing as t
from dataclasses import dataclass

if t.TYPE_CHECKING:
    import pathlib
    from collections.abc import Sequence

#: tmux escapes a byte in ``%output`` as a backslash plus three octal digits.
_CONTROL_OCTAL = re.compile(rb"\\([0-7]{3})")


def render_control_line(argv: Sequence[str]) -> str:
    """Render a tmux argv as a control-mode (``tmux -C``) command line.

    Each token is quoted for the control parser, but a standalone ``;`` separator
    is left bare so a folded ``a ; b`` chain dispatches as two commands instead of
    one command with a literal ``';'`` argument.

    Examples
    --------
    >>> render_control_line(("rename-window", "-t", "@1", "a b"))
    "rename-window -t @1 'a b'"
    >>> render_control_line(("rename-window", "a", ";", "kill-window", "@2"))
    'rename-window a ; kill-window @2'
    """
    return " ".join(token if token == ";" else shlex.quote(token) for token in argv)


def unescape_control_output(payload: str) -> bytes:
    r"""Decode a control-mode ``%output`` payload back to the bytes the pane wrote.

    tmux does not forward pane output verbatim: in a ``%output`` notification it
    writes every non-printable byte -- and the backslash itself -- as a backslash
    followed by three octal digits. A reader that scans for raw bytes must undo
    this first, or it can never match: an ``ESC`` (``0x1b``) arrives on the wire
    as the four *characters* ``\``, ``0``, ``3``, ``3``.

    Bytes tmux left alone pass through untouched, so feeding this an already-raw
    payload is harmless.

    Examples
    --------
    Printable output is returned as-is:

    >>> unescape_control_output("hello world")
    b'hello world'

    An escape sequence tmux octal-escaped comes back as real bytes:

    >>> unescape_control_output(r"\033]3008;state=idle\033\134")
    b'\x1b]3008;state=idle\x1b\\'

    Multi-byte UTF-8 survives the round trip:

    >>> unescape_control_output(r"caf\303\251").decode()
    'café'
    """
    raw = payload.encode("utf-8", "surrogateescape")
    return _CONTROL_OCTAL.sub(lambda m: bytes((int(m.group(1), 8),)), raw)


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
    MOCK = "mock"
    CONTROL_MODE = "control_mode"
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
    def mock(cls) -> EngineSpec:
        """Build a mock (in-memory) engine spec."""
        return cls(kind=EngineKind.MOCK)

    @classmethod
    def control_mode(cls) -> EngineSpec:
        """Build a control-mode engine spec."""
        return cls(kind=EngineKind.CONTROL_MODE)

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


@t.runtime_checkable
class SupportsTmuxVersion(t.Protocol):
    """An engine that can report the tmux version it targets.

    Optional engine capability. The executors
    (:func:`~libtmux.experimental.ops.execute.run` / ``arun`` and the
    :class:`~libtmux.experimental.ops.plan.LazyPlan` drivers) call
    :meth:`tmux_version` to resolve the version for version-gated rendering when
    the caller passes none. Engines that cannot know their version -- in-memory
    or fake engines -- simply do not implement it, and resolution falls back to
    "assume latest".
    """

    def tmux_version(self) -> str | None:
        """Return the engine's tmux version string, or ``None`` if unknown."""
        ...
