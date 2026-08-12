"""Core engine values: requests, results, argv encoding, and the protocols.

A :class:`CommandRequest` is a tmux argv (the subcommand and its arguments,
*without* connection flags); a :class:`CommandResult` is the structured outcome.
:class:`TmuxEngine` is a :class:`typing.Protocol`, so any object with ``run`` and
``run_batch`` is an engine -- an in-memory fake, a control-mode client, a
recorder -- without inheriting a base class.

The argv encoders live here because they describe tmux's own parser, not any one
transport: tmux strips client-global options with ``getopt`` before handing the
remainder to ``cmd_parse_from_arguments``, where a trailing ``;`` is a command
boundary rather than data.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field

if t.TYPE_CHECKING:
    import pathlib
    import subprocess
    from collections.abc import Sequence

    from typing_extensions import Self

# tmux parses these options with getopt before its command argv reaches
# cmd_parse_from_arguments. Only values in the latter have structural
# trailing-semicolon semantics.
_GLOBAL_OPTIONS_WITH_VALUE = frozenset({"c", "f", "L", "S", "T"})
_GLOBAL_OPTIONS_WITHOUT_VALUE = frozenset(
    {"2", "8", "C", "D", "d", "h", "l", "N", "q", "u", "U", "v", "V"},
)


class CommandSeparator(str):
    """A caller-authored command boundary, distinct from a literal ``";"``.

    Examples
    --------
    >>> CommandSeparator(";")
    ';'
    >>> CommandSeparator("kill-server")
    Traceback (most recent call last):
    ...
    ValueError: a command separator must be exactly ';'
    """

    def __new__(cls, value: str) -> Self:
        """Construct the one legal structural token.

        Parameters
        ----------
        value : str
            Must be ``";"``.

        Returns
        -------
        CommandSeparator
            The structural token.

        Examples
        --------
        >>> str(CommandSeparator(";"))
        ';'
        """
        if value != ";":
            msg = "a command separator must be exactly ';'"
            raise ValueError(msg)
        return super().__new__(cls, value)


def is_command_separator(token: str) -> bool:
    """Return whether *token* is an intentional tmux command boundary.

    Parameters
    ----------
    token : str
        A single argv token.

    Returns
    -------
    bool
        ``True`` only for a :class:`CommandSeparator`, never for a plain
        ``";"`` a caller meant as data.

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

    The split follows tmux's leading short-option ``getopt`` grammar, including
    attached values and ``--``. Global values remain byte-for-byte data because
    tmux removes them before parsing command separators.

    Parameters
    ----------
    argv : Sequence[str]
        tmux argv after the binary.

    Returns
    -------
    DirectArgv
        The global and command halves.

    Raises
    ------
    ValueError
        A token contains a NUL byte, which no tmux transport can carry.

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
    return tuple(
        f"{token[:-1]}\\;"
        if not is_command_separator(token) and token.endswith(";")
        else str(token)
        for token in argv
    )


def encode_direct_argv(argv: Sequence[str]) -> tuple[str, ...]:
    r"""Encode literal arguments for tmux's direct argv parser.

    tmux first removes client-global options, then routes only the remaining
    command argv through ``cmd_parse_from_arguments``, where a final ``;`` is
    structural. Prefixing that final byte with one backslash preserves it as
    data. Global option values are left alone, and a :class:`CommandSeparator`
    stays structural.

    Parameters
    ----------
    argv : Sequence[str]
        tmux argv after the binary.

    Returns
    -------
    tuple[str, ...]
        argv safe to hand to ``execve``.

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


@dataclass(frozen=True)
class CommandRequest:
    """A tmux command, ready for an engine to execute.

    Carries the subcommand and its arguments only. Connection flags
    (``-L``/``-S``/``-f``/``-2``/``-8``) belong to the engine's
    :class:`~libtmux.engines.connection.ServerConnection`, so every engine sees
    the same request no matter which tmux server it targets.

    Attributes
    ----------
    args : tuple[str, ...]
        The tmux argv (e.g. ``("split-window", "-t", "%1")``).
    tmux_bin : str or None
        Override the tmux binary for this one request; ``None`` lets the engine
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

    def __post_init__(self) -> None:
        r"""Reject arguments that cannot survive tmux's C-string transports.

        Examples
        --------
        >>> CommandRequest(args=("display-message", "a\0b"))
        Traceback (most recent call last):
        ...
        ValueError: tmux command arguments cannot contain NUL
        """
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
        """Build a request from arbitrary tokens, stringifying each.

        Parameters
        ----------
        *args : typing.Any
            Tokens; non-strings are rendered with :func:`str`, matching what
            :class:`~libtmux.common.tmux_cmd` has always accepted.
        tmux_bin : str or pathlib.Path, optional
            Per-request tmux binary override.

        Returns
        -------
        CommandRequest
            The request.

        Examples
        --------
        >>> CommandRequest.from_args("resize-pane", "-t", "%3", "-x", 80).args
        ('resize-pane', '-t', '%3', '-x', '80')
        """
        return cls(
            args=tuple(arg if isinstance(arg, str) else str(arg) for arg in args),
            tmux_bin=str(tmux_bin) if tmux_bin is not None else None,
        )

    @property
    def subcommand(self) -> str:
        """Return the tmux subcommand, or ``""`` for an empty request.

        Returns
        -------
        str
            First argv token.

        Examples
        --------
        >>> CommandRequest.from_args("list-sessions", "-F#S").subcommand
        'list-sessions'
        >>> CommandRequest.from_args().subcommand
        ''
        """
        return self.args[0] if self.args else ""


@dataclass(frozen=True)
class CommandResult:
    """The structured outcome of executing a :class:`CommandRequest`.

    A tmux-side failure (nonzero exit, message on stderr) is *data* here: it
    sets ``returncode`` and ``stderr`` rather than raising. Only a broken engine
    (missing binary, lost connection) raises.

    Attributes
    ----------
    cmd : tuple[str, ...]
        The full argv that ran, including the tmux binary and connection flags.
    stdout : tuple[str, ...]
        Captured standard-output lines, trailing blanks removed.
    stderr : tuple[str, ...]
        Captured standard-error lines, blanks removed.
    returncode : int
        tmux exit code.
    process : subprocess.Popen or None
        The OS process, when the engine forked one. ``None`` for engines that
        never touch the operating system, which is why
        :attr:`libtmux.common.tmux_cmd.process` can only be a best-effort
        accessor. Excluded from equality and :func:`repr`.

    Examples
    --------
    >>> CommandResult(cmd=("tmux", "display-message", "-p", "hi"), stdout=("hi",))
    CommandResult(cmd=('tmux', 'display-message', '-p', 'hi'), stdout=('hi',),
    stderr=(), returncode=0)
    """

    cmd: tuple[str, ...]
    stdout: tuple[str, ...] = ()
    stderr: tuple[str, ...] = ()
    returncode: int = 0
    process: subprocess.Popen[str] | None = field(
        default=None,
        compare=False,
        repr=False,
    )

    @property
    def ok(self) -> bool:
        """Whether tmux accepted the command.

        Returns
        -------
        bool
            ``True`` when :attr:`returncode` is zero.

        Examples
        --------
        >>> CommandResult(cmd=("tmux", "list-sessions")).ok
        True
        >>> CommandResult(cmd=("tmux", "kill-window"), returncode=1).ok
        False
        """
        return self.returncode == 0

    def raise_for_status(self) -> CommandResult:
        """Raise when tmux rejected the command, otherwise return self.

        Engines report a tmux-side failure as data so a caller can inspect it.
        This turns that data back into an exception at the point a caller would
        rather not continue, and returns ``self`` so it chains.

        Returns
        -------
        CommandResult
            This result, when :attr:`ok`.

        Raises
        ------
        :exc:`~libtmux.exc.LibTmuxException`
            tmux exited non-zero. The message carries tmux's own stderr.

        Examples
        --------
        >>> result = CommandResult(cmd=("tmux", "list-sessions"), stdout=("a",))
        >>> result.raise_for_status().stdout
        ('a',)

        The message names the tmux subcommand, not a connection flag:

        >>> CommandResult(
        ...     cmd=("tmux", "-Lmysocket", "kill-window", "-t", "@9"),
        ...     stderr=("can't find window @9",),
        ...     returncode=1,
        ... ).raise_for_status()
        Traceback (most recent call last):
        ...
        libtmux.exc.LibTmuxException: kill-window: can't find window @9
        """
        if self.ok:
            return self
        from libtmux import exc

        detail = " ".join(self.stderr) or f"exited {self.returncode}"
        # cmd is the full argv: binary, then client-global flags, then the
        # subcommand. Skip the flags the way tmux's own getopt does, so the
        # message names "kill-window" rather than "-Lmysocket".
        command_argv = split_direct_argv(self.cmd[1:]).command_argv
        subcommand = command_argv[0] if command_argv else "tmux"
        msg = f"{subcommand}: {detail}"
        raise exc.LibTmuxException(msg)


@t.runtime_checkable
class TmuxEngine(t.Protocol):
    """A synchronous executor of tmux commands.

    Structural: an object is an engine when it has ``run`` and ``run_batch``.
    Writing both is only necessary when you do *not* inherit — subclassing
    :class:`TmuxEngine` supplies :meth:`run_batch`, so a stateless engine needs
    just :meth:`run`.

    Examples
    --------
    Inheriting is the short way:

    >>> from libtmux.engines import CommandRequest, CommandResult, TmuxEngine
    >>> class EchoEngine(TmuxEngine):
    ...     def run(self, request):
    ...         return CommandResult(cmd=("tmux", *request.args), stdout=("ok",))
    >>> EchoEngine().run(CommandRequest.from_args("list-sessions")).stdout
    ('ok',)
    >>> EchoEngine().run_batch([CommandRequest.from_args("list-sessions")])
    [CommandResult(cmd=('tmux', 'list-sessions'), stdout=('ok',), stderr=(),
    returncode=0)]

    Duck typing works too, but then both methods are yours to write:

    >>> class Structural:
    ...     def run(self, request):
    ...         return CommandResult(cmd=("tmux", *request.args))
    ...
    ...     def run_batch(self, requests):
    ...         return [self.run(request) for request in requests]
    >>> isinstance(Structural(), TmuxEngine)
    True
    """

    def run(self, request: CommandRequest) -> CommandResult:
        """Execute one tmux command and return its structured result."""
        ...

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Execute requests in order, returning one result per request.

        Defaults to a loop over :meth:`run`, which is correct for any stateless
        engine. Nothing in libtmux calls it yet -- :meth:`Server.cmd
        <libtmux.Server.cmd>` dispatches one command at a time -- but it is not
        dead weight: it is the hook a persistent-connection engine overrides to
        pipeline a batch down one ``tmux -C`` connection without waiting for
        each reply, which is where the round-trip savings live. Removing it
        would have to be undone as a breaking protocol change the moment such an
        engine lands.

        Parameters
        ----------
        requests : Sequence[CommandRequest]
            Requests to run, in order.

        Returns
        -------
        list[CommandResult]
            One result per request.
        """
        return [self.run(request) for request in requests]


@t.runtime_checkable
class AsyncTmuxEngine(t.Protocol):
    """An asynchronous executor of tmux commands.

    The async sibling of :class:`TmuxEngine`, declared here so an async engine
    has a type to satisfy from the day it is written rather than after the fact.
    {class}`~libtmux.Server` is synchronous and does **not** accept one; it is
    for callers driving tmux on an event loop directly, and for the engines that
    will hold a persistent ``tmux -C`` connection.

    Examples
    --------
    >>> import asyncio
    >>> from libtmux.engines import AsyncTmuxEngine, CommandRequest, CommandResult
    >>> class AsyncEcho(AsyncTmuxEngine):
    ...     async def run(self, request):
    ...         return CommandResult(cmd=("tmux", *request.args), stdout=("ok",))
    >>> async def main():
    ...     engine = AsyncEcho()
    ...     result = await engine.run(CommandRequest.from_args("list-sessions"))
    ...     batch = await engine.run_batch([CommandRequest.from_args("list-panes")])
    ...     return result.stdout, len(batch)
    >>> asyncio.run(main())
    (('ok',), 1)
    """

    async def run(self, request: CommandRequest) -> CommandResult:
        """Execute one tmux command and return its structured result."""
        ...

    async def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Execute requests in order, returning one result per request.

        Defaults to an awaited loop over :meth:`run`. A persistent-connection
        engine overrides it to pipeline without waiting for each reply.

        Parameters
        ----------
        requests : Sequence[CommandRequest]
            Requests to run, in order.

        Returns
        -------
        list[CommandResult]
            One result per request.
        """
        return [await self.run(request) for request in requests]


@t.runtime_checkable
class SupportsCommandLine(t.Protocol):
    """An engine that can render the argv it *would* run, without running it.

    Optional capability. :class:`~libtmux.common.tmux_cmd` uses it to log the
    full command line before dispatch; engines without a command line (in-memory
    fakes) simply do not implement it.

    Examples
    --------
    >>> from libtmux.engines import SupportsCommandLine, SubprocessEngine
    >>> isinstance(SubprocessEngine.for_server(server), SupportsCommandLine)
    True
    """

    def command_line(self, request: CommandRequest) -> tuple[str, ...]:
        """Return the full argv, binary first, that *request* would run as."""
        ...


@t.runtime_checkable
class SupportsConnection(t.Protocol):
    """An engine that dispatches over a named tmux server and can be rebound.

    Optional capability. :attr:`Server.engine <libtmux.Server.engine>` reads it
    so an injected engine that names no server of its own adopts the server's
    connection instead of silently reaching the ambient tmux server. In-memory
    engines have no connection and simply do not implement it.

    Examples
    --------
    >>> from libtmux.engines import SubprocessEngine, SupportsConnection
    >>> isinstance(SubprocessEngine(), SupportsConnection)
    True

    An engine with no notion of a socket does not implement it:

    >>> class InMemoryEngine:
    ...     def run(self, request):
    ...         return CommandResult(cmd=("tmux", *request.args))
    ...     def run_batch(self, requests):
    ...         return [self.run(r) for r in requests]
    >>> isinstance(InMemoryEngine(), SupportsConnection)
    False
    """

    @property
    def connection(self) -> t.Any:
        """Return the tmux binary and flags this engine dispatches over."""
        ...

    def with_connection(self, connection: t.Any) -> TmuxEngine:
        """Return an equivalent engine bound to *connection*."""
        ...


@t.runtime_checkable
class SupportsTmuxVersion(t.Protocol):
    """An engine that can report the tmux version it targets.

    Optional capability, for version-gated rendering. Engines that cannot know
    their version -- in-memory fakes -- do not implement it, and callers fall
    back to "assume latest".

    Examples
    --------
    >>> from libtmux.engines import SubprocessEngine, SupportsTmuxVersion
    >>> isinstance(SubprocessEngine.for_server(server), SupportsTmuxVersion)
    True
    """

    def tmux_version(self) -> str | None:
        """Return the engine's tmux version string, or ``None`` if unknown."""
        ...
