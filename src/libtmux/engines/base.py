"""Core engine values: requests, results, and the protocols.

A :class:`CommandRequest` is a tmux argv (the subcommand and its arguments,
*without* connection flags); a :class:`CommandResult` is the structured outcome.
:class:`TmuxEngine` is a :class:`typing.Protocol`, so any object with ``run`` and
``run_batch`` is an engine -- an in-memory fake, a control-mode client, a
recorder -- without inheriting a base class.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field

if t.TYPE_CHECKING:
    import pathlib
    import subprocess
    from collections.abc import Sequence

    from typing_extensions import Self

    from libtmux.engines.connection import ServerConnection


class CommandSeparator(str):
    """A caller-authored command boundary, distinct from a literal ``";"``.

    Tmux's direct argv parser treats any unescaped trailing ``;`` as command
    structure, including a suffix on a larger value. A literal suffix -- a pane
    title or shell fragment passed to ``send-keys`` -- must not become one.
    Marking a real boundary with its own type lets direct engines escape
    ordinary values while rendering intentional command groups structurally.

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
            Must be exactly ``";"``.

        Returns
        -------
        CommandSeparator
            The separator.

        Raises
        ------
        ValueError
            *value* is anything other than ``";"``.
        """
        if value != ";":
            msg = "a command separator must be exactly ';'"
            raise ValueError(msg)
        return super().__new__(cls, value)


def is_command_separator(token: str) -> bool:
    """Return whether *token* is an intentional tmux command boundary.

    A plain ``";"`` is data and answers ``False``; only a
    :class:`CommandSeparator` answers ``True``.

    Parameters
    ----------
    token : str
        The argv token to test.

    Returns
    -------
    bool

    Examples
    --------
    >>> is_command_separator(CommandSeparator(";"))
    True
    >>> is_command_separator(";")
    False
    """
    return type(token) is CommandSeparator and token == ";"


def command_count(argv: tuple[str, ...]) -> int:
    """Return how many tmux commands a rendered *argv* runs.

    A command group is one argv carrying several commands, separated by
    :class:`CommandSeparator`, so the count is the separators plus one. Callers
    that measure engine traffic need this to tell a request that ran one tmux
    command from a request that inlined several into a single dispatch.

    Parameters
    ----------
    argv : tuple of str
        A request's arguments, before any engine-specific encoding.

    Returns
    -------
    int

    Examples
    --------
    >>> command_count(("list-panes", "-a"))
    1
    >>> group = ("set-option", "-g", "@x", "1", CommandSeparator(";"), "show-options")
    >>> command_count(group)
    2

    A literal ``";"`` is data, not a boundary, so it does not add a command:

    >>> command_count(("send-keys", ";"))
    1
    """
    return sum(1 for token in argv if is_command_separator(token)) + 1


@dataclass(frozen=True)
class CommandRequest:
    """A tmux command, ready for an engine to execute.

    Carries the subcommand and its arguments only. Connection flags
    (``-L``/``-S``/``-f``/``-2``) belong to the engine's
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

        A :class:`CommandSeparator` keeps its type through normalization, so a
        chaining engine can still find the boundary:

        >>> request = CommandRequest(args=("kill-window", CommandSeparator(";")))
        >>> [is_command_separator(arg) for arg in request.args]
        [False, True]

        A separator whose value was forged past :meth:`CommandSeparator.__new__`
        is rejected rather than passed through as structural, so it cannot
        smuggle a second command into a chained dispatch:

        >>> CommandRequest.from_args("display-message", str.__new__(
        ...     CommandSeparator, "\nkill-server"))
        Traceback (most recent call last):
        ...
        ValueError: a command separator must be exactly ';'
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


@t.runtime_checkable
class TmuxEngine(t.Protocol):
    """A synchronous executor of tmux commands.

    Structural: an object is an engine when it has ``run`` and ``run_batch``.

    Examples
    --------
    >>> from libtmux.engines import CommandRequest, CommandResult, TmuxEngine
    >>> class EchoEngine:
    ...     def run(self, request):
    ...         return CommandResult(cmd=("tmux", *request.args), stdout=("ok",))
    ...
    ...     def run_batch(self, requests):
    ...         return [self.run(request) for request in requests]
    >>> isinstance(EchoEngine(), TmuxEngine)
    True
    >>> EchoEngine().run(CommandRequest.from_args("list-sessions")).stdout
    ('ok',)
    """

    def run(self, request: CommandRequest) -> CommandResult:
        """Execute one tmux command and return its structured result."""
        ...

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Execute requests in order, returning one result per request.

        Persistent-connection engines override this to pipeline; stateless
        engines implement it as a loop over :meth:`run`.
        """
        ...


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
class HasConnection(t.Protocol):
    """An engine whose tmux connection can be inspected without changing it.

    Persistent engines implement this read-only capability even though their
    live transport cannot be cloned safely. In-memory engines with no tmux
    connection omit it.

    Examples
    --------
    >>> from libtmux.engines import HasConnection, SubprocessEngine
    >>> isinstance(SubprocessEngine(), HasConnection)
    True
    """

    @property
    def connection(self) -> ServerConnection:
        """Return the tmux binary and global flags this engine uses."""
        ...


@t.runtime_checkable
class SupportsConnection(HasConnection, t.Protocol):
    """An inspectable engine that can safely return a rebound equivalent.

    Optional capability. Stateless subprocess engines implement it. Persistent
    transports expose :class:`HasConnection` only, because cloning one could
    duplicate or abandon live connection state.

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

    def with_connection(self, connection: ServerConnection) -> Self:
        """Return an equivalent engine bound to *connection*."""
        ...


@t.runtime_checkable
class SupportsTmuxVersion(t.Protocol):
    """An engine that can report the tmux version it targets.

    Optional capability. Callers that render version-gated argv -- dropping a
    flag an older tmux cannot accept -- read it to resolve the version when
    none is passed. Engines that cannot know their version, such as in-memory
    fakes, simply do not implement it, and resolution falls back to assuming
    the newest tmux.

    Examples
    --------
    >>> from libtmux.engines import SubprocessEngine, SupportsTmuxVersion
    >>> isinstance(SubprocessEngine.for_server(server), SupportsTmuxVersion)
    True
    """

    def tmux_version(self) -> str | None:
        """Return the engine's tmux version string, or ``None`` if unknown."""
        ...
