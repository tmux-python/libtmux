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

from libtmux.engines.base import (
    CommandRequest,
    CommandResult,
    CommandSeparator,
    SupportsTmuxVersion,
    TmuxEngine,
    is_command_separator,
)

if t.TYPE_CHECKING:
    from collections.abc import Sequence


#: tmux escapes a byte in ``%output`` as a backslash plus three octal digits.
_CONTROL_OCTAL = re.compile(rb"\\([0-7]{3})")

# tmux parses these options with getopt before its command argv reaches
# cmd_parse_from_arguments. Only values in the latter have structural
# trailing-semicolon semantics.
_GLOBAL_OPTIONS_WITH_VALUE = frozenset({"c", "f", "L", "S", "T"})
_GLOBAL_OPTIONS_WITHOUT_VALUE = frozenset(
    {"2", "8", "C", "D", "d", "h", "l", "N", "q", "u", "U", "v", "V"},
)

__all__ = (
    "AsyncTmuxEngine",
    "CommandRequest",
    "CommandResult",
    "CommandSeparator",
    "DirectArgv",
    "EngineKind",
    "EngineSpec",
    "SupportsTmuxVersion",
    "TmuxEngine",
    "encode_direct_argv",
    "is_command_separator",
    "render_control_line",
    "split_direct_argv",
    "unescape_control_output",
)


class DirectArgv(t.NamedTuple):
    """The client-global and command portions of direct tmux argv.

    Attributes
    ----------
    global_args : tuple[str, ...]
        Leading options consumed by tmux's client-level ``getopt`` parser.
    command_argv : tuple[str, ...]
        The subcommand and arguments passed to ``cmd_parse_from_arguments``.
    """

    global_args: tuple[str, ...]
    command_argv: tuple[str, ...]


def _global_option_consumes_next(token: str) -> bool | None:
    """Return a global option's separate-value arity, or ``None`` if unknown.

    Examples
    --------
    >>> _global_option_consumes_next("-L")
    True
    >>> _global_option_consumes_next("-Lwork")
    False
    >>> _global_option_consumes_next("list-sessions") is None
    True
    """
    if not token.startswith("-") or token in {"-", "--"}:
        return None
    cluster = token[1:]
    if not cluster:
        return None
    for index, option in enumerate(cluster):
        if option in _GLOBAL_OPTIONS_WITH_VALUE:
            return index == len(cluster) - 1
        if option not in _GLOBAL_OPTIONS_WITHOUT_VALUE:
            return None
    return False


def split_direct_argv(argv: Sequence[str]) -> DirectArgv:
    """Split raw tmux argv at the client-global/command parser boundary.

    The split follows tmux's leading short-option ``getopt`` grammar, including
    attached values and ``--``. Global values remain byte-for-byte data because
    tmux removes them before parsing command separators.

    Examples
    --------
    >>> split_direct_argv(("-L", "socket;", "display-message", "text;"))
    DirectArgv(global_args=('-L', 'socket;'), command_argv=('display-message', 'text;'))
    >>> split_direct_argv(("-Lsocket;", "--", "display-message"))
    DirectArgv(global_args=('-Lsocket;', '--'), command_argv=('display-message',))
    """
    args = tuple(argv)
    if any("\0" in token for token in args):
        msg = "tmux command arguments cannot contain NUL"
        raise ValueError(msg)

    index = 0
    while index < len(args):
        token = args[index]
        if token == "--":
            index += 1
            break
        consumes_next = _global_option_consumes_next(token)
        if consumes_next is None:
            break
        index += 2 if consumes_next and index + 1 < len(args) else 1
    return DirectArgv(global_args=args[:index], command_argv=args[index:])


def _encode_command_argv(argv: Sequence[str]) -> tuple[str, ...]:
    r"""Escape literal separators in argv already known to be command-scoped.

    Examples
    --------
    >>> _encode_command_argv(("display-message", "literal;"))
    ('display-message', 'literal\\;')
    """
    encoded: list[str] = []
    for token in argv:
        if not is_command_separator(token) and token.endswith(";"):
            token = f"{token[:-1]}\\;"
        encoded.append(str(token))
    return tuple(encoded)


def encode_direct_argv(argv: Sequence[str]) -> tuple[str, ...]:
    r"""Encode literal arguments for tmux's direct argv parser.

    Tmux first removes client-global options, then routes only the remaining
    command argv through ``cmd_parse_from_arguments``, where a final ``;`` is
    structural. Prefixing that final byte with one backslash preserves it as
    data. Global option values remain unchanged, and a
    :class:`CommandSeparator` remains structural.

    Examples
    --------
    >>> encode_direct_argv(("send-keys", "text;"))
    ('send-keys', 'text\\;')
    >>> encode_direct_argv(("-L", "socket;", "send-keys", "text;"))
    ('-L', 'socket;', 'send-keys', 'text\\;')
    >>> encode_direct_argv(("a", CommandSeparator(";"), "b"))
    ('a', ';', 'b')
    """
    direct = split_direct_argv(argv)
    return (*direct.global_args, *_encode_command_argv(direct.command_argv))


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
