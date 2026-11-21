"""Engine abstractions for :mod:`libtmux.experimental` atop :mod:`libtmux.engine`.

Bridges experimental ``CommandRequest`` / ``CommandResult`` operations with
Core's raw-byte :class:`~libtmux.engine.TmuxRequest` and
:class:`~libtmux.engine.TmuxResult` values so experimental engines plug into
both :mod:`libtmux.experimental.ops` and :class:`~libtmux.Server`.
"""

from __future__ import annotations

import enum
import re
import shlex
import typing as t
from dataclasses import dataclass

from libtmux._internal.protocols import (
    HasConnection,
    SupportsConnection,
    SupportsTmuxVersion,
)
from libtmux.engine import TmuxRequest, TmuxResult

if t.TYPE_CHECKING:
    import pathlib
    from collections.abc import Sequence
    from typing import Self

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
    "HasConnection",
    "SupportsAsyncTmuxVersion",
    "SupportsConnection",
    "SupportsTmuxVersion",
    "TmuxEngine",
    "command_count",
    "encode_command_argv",
    "encode_direct_argv",
    "is_command_separator",
    "render_control_line",
    "split_direct_argv",
    "unescape_control_output",
)


class CommandSeparator(str):
    """A planner-authored command boundary, distinct from a literal ``";"``.

    Examples
    --------
    >>> CommandSeparator(";")
    ';'
    >>> CommandSeparator("kill-server")
    Traceback (most recent call last):
    ...
    ValueError: a command separator must be exactly ';'
    """

    __slots__ = ()

    def __new__(cls, value: str) -> Self:
        """Construct the one legal structural token."""
        if value != ";":
            msg = "a command separator must be exactly ';'"
            raise ValueError(msg)
        return super().__new__(cls, value)


def is_command_separator(token: str) -> bool:
    """Return whether *token* is an intentional tmux command boundary.

    Examples
    --------
    >>> is_command_separator(CommandSeparator(";"))
    True
    >>> is_command_separator(";")
    False
    """
    return type(token) is CommandSeparator and token == ";"


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


def encode_command_argv(argv: Sequence[str]) -> tuple[str, ...]:
    r"""Escape literal separators in argv already known to be command-scoped.

    Examples
    --------
    >>> encode_command_argv(("display-message", "literal;"))
    ('display-message', 'literal\\;')
    >>> encode_command_argv(("display-message", "escaped\\;"))
    ('display-message', 'escaped\\;')
    """
    encoded: list[str] = []
    for token in argv:
        if (
            not is_command_separator(token)
            and token.endswith(";")
            and not token.endswith(r"\;")
        ):
            token = f"{token[:-1]}\\;"
        encoded.append(str(token))
    return tuple(encoded)


def command_count(argv: Sequence[str] | CommandRequest) -> int:
    """Return the number of tmux commands in *argv* or *request*.

    Examples
    --------
    >>> command_count(("list-panes", "-a"))
    1
    >>> command_count(
    ...     ("set-option", "-g", "@x", "1", CommandSeparator(";"), "list-panes")
    ... )
    2
    """
    tokens = argv.args if isinstance(argv, CommandRequest) else argv
    direct = split_direct_argv(tokens)
    if not direct.command_argv:
        return 0
    return 1 + sum(1 for tok in direct.command_argv if is_command_separator(tok))


def encode_direct_argv(argv: Sequence[str]) -> tuple[str, ...]:
    r"""Encode literal arguments for tmux's direct argv parser.

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
    return (*direct.global_args, *encode_command_argv(direct.command_argv))


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

    Examples
    --------
    >>> unescape_control_output("hello world")
    b'hello world'
    >>> unescape_control_output(r"\033]3008;state=idle\033\134")
    b'\x1b]3008;state=idle\x1b\\'
    >>> unescape_control_output(r"caf\303\251").decode()
    'café'
    """
    raw = (
        payload.encode("utf-8", "surrogateescape")
        if isinstance(payload, str)
        else payload
    )
    return _CONTROL_OCTAL.sub(lambda m: bytes((int(m.group(1), 8),)), raw)


@dataclass(frozen=True)
class CommandRequest:
    """A rendered tmux command for :mod:`libtmux.experimental.ops` engines.

    Attributes
    ----------
    args : tuple[str, ...]
        The tmux argv after the binary.
    tmux_bin : str or None
        Optional per-request tmux executable override.

    Examples
    --------
    >>> CommandRequest.from_args("split-window", "-t", "%1")
    CommandRequest(args=('split-window', '-t', '%1'), tmux_bin=None)
    """

    args: tuple[str, ...]
    tmux_bin: str | None = None

    def __post_init__(self) -> None:
        r"""Reject arguments that cannot survive tmux's C-string transports.

        Examples
        --------
        >>> CommandRequest(args=("display-message", "a\0b"))
        Traceback (most recent call last):
        ...
        ValueError: tmux command arguments cannot contain NUL
        """
        if any(
            type(arg) is CommandSeparator and not is_command_separator(arg)
            for arg in self.args
        ):
            msg = "a command separator must be exactly ';'"
            raise ValueError(msg)
        normalized = tuple(
            arg if is_command_separator(arg) else str.__str__(arg) for arg in self.args
        )
        if any("\0" in arg for arg in normalized):
            msg = "tmux command arguments cannot contain NUL"
            raise ValueError(msg)
        object.__setattr__(self, "args", normalized)

    @classmethod
    def from_args(
        cls,
        *args: t.Any,
        tmux_bin: str | pathlib.Path | None = None,
    ) -> CommandRequest:
        """Build a request from arbitrary tokens, stringifying each."""
        return cls(
            args=tuple(arg if isinstance(arg, str) else str(arg) for arg in args),
            tmux_bin=str(tmux_bin) if tmux_bin is not None else None,
        )

    @property
    def subcommand(self) -> str:
        """First subcommand token after client-global options, or ``""``."""
        direct = split_direct_argv(self.args)
        return str(direct.command_argv[0]) if direct.command_argv else ""

    @classmethod
    def from_tmux_request(cls, request: TmuxRequest) -> CommandRequest:
        """Convert a Core :class:`~libtmux.engine.TmuxRequest` to ``CommandRequest``."""
        tokens: list[str] = list(request.client_args)
        for index, cmd in enumerate(request.commands):
            if index > 0:
                tokens.append(CommandSeparator(";"))
            tokens.extend(cmd)
        return cls(args=tuple(tokens), tmux_bin=request.tmux_bin)

    def to_tmux_request(self) -> TmuxRequest:
        """Convert this request into a Core :class:`~libtmux.engine.TmuxRequest`."""
        direct = split_direct_argv(self.args)
        commands: list[tuple[str, ...]] = []
        current: list[str] = []
        for token in direct.command_argv:
            if is_command_separator(token):
                if current:
                    commands.append(tuple(current))
                    current = []
            else:
                current.append(str.__str__(token))
        if current:
            commands.append(tuple(current))
        return TmuxRequest(
            commands=tuple(commands),
            client_args=direct.global_args,
            tmux_bin=self.tmux_bin,
        )


@dataclass(frozen=True)
class CommandResult:
    """Structured line-decoded outcome of executing a :class:`CommandRequest`.

    Attributes
    ----------
    cmd : tuple[str, ...]
        Full argv that ran.
    stdout : tuple[str, ...]
        Captured standard-output lines.
    stderr : tuple[str, ...]
        Captured standard-error lines.
    returncode : int
        Exit status reported by tmux.
    """

    cmd: tuple[str, ...]
    stdout: tuple[str, ...] = ()
    stderr: tuple[str, ...] = ()
    returncode: int = 0

    @classmethod
    def from_tmux_result(cls, result: TmuxResult) -> CommandResult:
        """Decode a Core :class:`~libtmux.engine.TmuxResult` into lines."""
        out_lines = result.stdout.decode("utf-8", errors="backslashreplace").split("\n")
        while out_lines and out_lines[-1] == "":
            out_lines.pop()
        err_lines = [
            line
            for line in result.stderr.decode("utf-8", errors="backslashreplace").split(
                "\n"
            )
            if line
        ]
        return cls(
            cmd=tuple(result.argv),
            stdout=tuple(out_lines),
            stderr=tuple(err_lines),
            returncode=result.returncode,
        )

    def to_tmux_result(self) -> TmuxResult:
        """Encode this line result into a Core :class:`~libtmux.engine.TmuxResult`."""
        raw_out = (
            ("\n".join(self.stdout) + "\n").encode("utf-8") if self.stdout else b""
        )
        raw_err = (
            ("\n".join(self.stderr) + "\n").encode("utf-8") if self.stderr else b""
        )
        return TmuxResult(
            argv=tuple(self.cmd),
            stdout=raw_out,
            stderr=raw_err,
            returncode=self.returncode,
        )


class EngineKind(enum.StrEnum):
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
    """Async engine capable of reporting its connected tmux version."""

    async def atmux_version(self) -> str | None:
        """Return the raw tmux version string asynchronously, or ``None``."""
        ...


@t.runtime_checkable
class TmuxEngine(t.Protocol):
    """Synchronous executor of experimental :class:`CommandRequest` commands."""

    def run(self, request: CommandRequest) -> CommandResult:
        """Execute one tmux command and return its structured result."""
        ...

    def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Execute requests in order, returning one result per request."""
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
