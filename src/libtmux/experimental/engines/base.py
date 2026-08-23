"""Engine abstractions the experimental layer adds on top of Core's seam.

:class:`~libtmux.engines.base.CommandRequest`,
:class:`~libtmux.engines.base.CommandResult`,
:class:`~libtmux.engines.base.TmuxEngine` and the separator values live in
Core's :mod:`libtmux.engines` and are re-exported here, so an experimental
engine and Core's object API exchange the same values -- an engine written
against either import path plugs into :class:`libtmux.Server`.

What remains local is what only the experimental transports need: the argv
encoders that split tmux's client-global options from its command argv,
control-mode line rendering and unescaping, the serializable
:class:`EngineSpec` selector, and the asynchronous
:class:`AsyncTmuxEngine` protocol.
"""

from __future__ import annotations

import enum
import re
import shlex
import typing as t
from dataclasses import dataclass

from libtmux._internal.tmux_argv import (
    DirectArgv,
    encode_direct_argv,
    split_direct_argv,
)
from libtmux.engines.base import (
    CommandRequest,
    CommandResult,
    CommandSeparator,
    HasConnection,
    SupportsConnection,
    SupportsTmuxVersion,
    TmuxEngine,
    is_command_separator,
)

if t.TYPE_CHECKING:
    from collections.abc import Sequence


#: tmux escapes a byte in ``%output`` as a backslash plus three octal digits.
_CONTROL_OCTAL = re.compile(rb"\\([0-7]{3})")

__all__ = (
    "AsyncTmuxEngine",
    "CommandRequest",
    "CommandResult",
    "CommandSeparator",
    "DirectArgv",
    "EngineKind",
    "EngineSpec",
    "HasConnection",
    "SupportsAsyncTmuxVersion",
    "SupportsConnection",
    "SupportsTmuxVersion",
    "TmuxEngine",
    "encode_direct_argv",
    "is_command_separator",
    "render_control_line",
    "split_direct_argv",
    "unescape_control_output",
)


def _quote_control_token(token: str) -> str:
    r"""Quote one literal token for tmux's line-oriented control parser."""
    if "\0" in token:
        msg = "tmux command arguments cannot contain NUL"
        raise ValueError(msg)
    if "\n" in token or "\r" in token:
        return "".join(f"\\{byte:03o}" for byte in token.encode())
    return shlex.quote(token)


def render_control_line(argv: Sequence[str]) -> str:
    r"""Render a tmux argv as a control-mode (``tmux -C``) command line.

    Literal tokens are quoted for the control parser. Tokens containing a line
    delimiter are UTF-8 octal encoded so one request remains one physical line.
    Only a :class:`CommandSeparator` is left bare.

    Examples
    --------
    >>> render_control_line(("rename-window", "-t", "@1", "a b"))
    "rename-window -t @1 'a b'"
    >>> render_control_line(
    ...     ("rename-window", "a", CommandSeparator(";"), "kill-window", "@2")
    ... )
    'rename-window a ; kill-window @2'
    >>> "\n" not in render_control_line(("display-message", "first\nsecond"))
    True
    """
    return " ".join(
        str(token) if is_command_separator(token) else _quote_control_token(token)
        for token in argv
    )


def unescape_control_output(payload: str | bytes) -> bytes:
    r"""Decode a control-mode ``%output`` payload back to the bytes the pane wrote.

    tmux does not forward pane output verbatim: in a ``%output`` notification it
    writes every non-printable byte -- and the backslash itself -- as a backslash
    followed by three octal digits. A reader that scans for raw bytes must undo
    this first, or it can never match: an ``ESC`` (``0x1b``) arrives on the wire
    as the four *characters* ``\``, ``0``, ``3``, ``3``.

    Bytes outside an exact three-digit escape pass through untouched. Apply the
    decoder once to wire data; it is not idempotent when decoded pane bytes
    themselves contain a backslash followed by three octal digits.

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
    raw = (
        payload.encode("utf-8", "surrogateescape")
        if isinstance(payload, str)
        else payload
    )
    return _CONTROL_OCTAL.sub(lambda m: bytes((int(m.group(1), 8),)), raw)


class EngineKind(str, enum.Enum):
    """Named engine families."""

    SUBPROCESS = "subprocess"
    MOCK = "mock"
    CONTROL_MODE = "control_mode"
    IMSG = "imsg"


@dataclass(frozen=True)
class EngineSpec:
    """A typed, serializable selector for an engine family.

    Attributes
    ----------
    kind : EngineKind
        Selected engine family.
    protocol_version : int or None
        Native imsg protocol version, valid only for the imsg engine.

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
class SupportsAsyncTmuxVersion(t.Protocol):
    """An async engine that can report its tmux version without blocking.

    Examples
    --------
    >>> class Versioned:
    ...     async def atmux_version(self):
    ...         return "3.4"
    >>> isinstance(Versioned(), SupportsAsyncTmuxVersion)
    True
    """

    async def atmux_version(self) -> str | None:
        """Return the engine's tmux version string, or ``None`` if unknown."""
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
