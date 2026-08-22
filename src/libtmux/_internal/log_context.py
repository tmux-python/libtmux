"""Structured logging context for :mod:`libtmux`.

Pure helpers that turn a tmux command line, or a tmux object's identity, into
the ``extra`` mapping libtmux attaches to its log records. Nothing here runs
tmux or touches a logger, so the record schema is testable without a server.
"""

from __future__ import annotations

import shlex
import typing as t

if t.TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = (
    "REDACTED",
    "CommandContext",
    "describe_command",
    "object_extra",
)

REDACTED = "REDACTED"
"""Placeholder substituted for environment values in logged command lines.

Chosen to survive :func:`shlex.join` unquoted, so quoting in a logged command
line still marks a genuinely quoted argument.
"""

_VALUE_FLAGS = frozenset("cfLST")
"""tmux global flags that consume the argument after them.

Mirrors the ``getopt`` string in tmux's ``tmux.c`` (``2c:CDdf:hlL:NqS:T:uUvV``).
Every other global flag is a boolean and may be bundled, as in ``-2q``.
"""

_SOCKET_FLAGS = frozenset("LS")

_ENV_SUBCOMMANDS = frozenset(
    {
        "new-session",
        "new-window",
        "respawn-pane",
        "respawn-window",
        "split-window",
    },
)
"""Subcommands whose ``-e`` carries a ``NAME=VALUE`` pair.

``select-pane -e`` and ``copy-mode -e`` are booleans, so a bare ``-e`` is never
read as an environment pair.
"""

_SETENV_SUBCOMMANDS = frozenset({"set-environment", "setenv"})
"""Subcommands shaped ``[-Fhgru] [-t target] variable [value]``."""


class CommandContext(t.NamedTuple):
    """Logging context derived from a tmux command line.

    Attributes
    ----------
    subcommand : str | None
        tmux subcommand, e.g. ``"new-session"``. ``None`` when the command line
        carries only global flags, as ``tmux -V`` does.
    socket : str | None
        Socket name (``-L``) or path (``-S``) identifying which tmux server the
        command addressed. ``None`` when tmux would use its default socket.
    command : str
        Shell-quoted command line with environment values replaced by
        :data:`REDACTED`.
    """

    subcommand: str | None
    socket: str | None
    command: str


def describe_command(argv: Sequence[str]) -> CommandContext:
    """Derive logging context from a tmux command line.

    Parameters
    ----------
    argv : Sequence[str]
        Full argument vector, beginning with the tmux binary.

    Returns
    -------
    CommandContext
        Subcommand, socket, and a redacted command string.

    Examples
    --------
    Global flags are skipped to reach the subcommand:

    >>> describe_command(["tmux", "-Lmysock", "new-session", "-d"])
    CommandContext(subcommand='new-session', socket='mysock', command='tmux -Lmysock new-session -d')

    Flags that take a value are understood in both joined and separated form,
    so the value is never mistaken for the subcommand:

    >>> describe_command(["tmux", "-L", "mysock", "kill-server"]).subcommand
    'kill-server'

    A command line with no subcommand reports ``None``:

    >>> describe_command(["tmux", "-V"]).subcommand is None
    True

    Environment values are redacted, and their names kept:

    >>> describe_command(
    ...     ["tmux", "new-session", "-eAPI_TOKEN=hunter2"]
    ... ).command
    'tmux new-session -eAPI_TOKEN=REDACTED'
    """  # noqa: E501
    tokens = [str(arg) for arg in argv]
    subcommand: str | None = None
    socket: str | None = None
    subcommand_index = len(tokens)

    index = 1
    while index < len(tokens):
        token = tokens[index]
        body = token[1:]
        if not token.startswith("-") or not body:
            subcommand = token
            subcommand_index = index
            break
        # Booleans bundle, so a value flag can sit anywhere in the token and
        # takes the remainder of it — or the next token when it ends there.
        takes_next_token = False
        for position, flag in enumerate(body):
            if flag not in _VALUE_FLAGS:
                continue
            joined_value = body[position + 1 :]
            value = joined_value or (
                tokens[index + 1] if index + 1 < len(tokens) else None
            )
            if flag in _SOCKET_FLAGS:
                socket = value
            takes_next_token = not joined_value
            break
        index += 2 if takes_next_token else 1

    return CommandContext(
        subcommand=subcommand,
        socket=socket,
        command=shlex.join(_redact(tokens, subcommand, subcommand_index)),
    )


def _redact(
    tokens: list[str],
    subcommand: str | None,
    subcommand_index: int,
) -> list[str]:
    """Return ``tokens`` with environment values replaced.

    Examples
    --------
    >>> _redact(["tmux", "new-session", "-eK=v"], "new-session", 1)
    ['tmux', 'new-session', '-eK=REDACTED']

    A boolean ``-e`` keeps the argument that follows it:

    >>> _redact(["tmux", "select-pane", "-e", "-t%1"], "select-pane", 1)
    ['tmux', 'select-pane', '-e', '-t%1']
    """
    if subcommand in _SETENV_SUBCOMMANDS:
        return _redact_set_environment(tokens, subcommand_index)

    redacted = list(tokens)
    separated_pairs = subcommand in _ENV_SUBCOMMANDS
    index = subcommand_index + 1
    while index < len(redacted):
        token = redacted[index]
        if token.startswith("-e") and "=" in token[2:]:
            name = token[2:].split("=", 1)[0]
            redacted[index] = f"-e{name}={REDACTED}"
        elif separated_pairs and token == "-e" and index + 1 < len(redacted):
            following = redacted[index + 1]
            if "=" in following:
                redacted[index + 1] = f"{following.split('=', 1)[0]}={REDACTED}"
            index += 1
        index += 1
    return redacted


def _redact_set_environment(tokens: list[str], subcommand_index: int) -> list[str]:
    """Return ``tokens`` with a ``set-environment`` value replaced.

    tmux reads ``set-environment [-Fhgru] [-t target-session] variable [value]``,
    so only a trailing second positional is a value worth hiding.

    Examples
    --------
    >>> _redact_set_environment(["tmux", "set-environment", "K", "v"], 1)
    ['tmux', 'set-environment', 'K', 'REDACTED']

    Unsetting passes a name and no value, which stays visible:

    >>> _redact_set_environment(["tmux", "set-environment", "-u", "K"], 1)
    ['tmux', 'set-environment', '-u', 'K']
    """
    redacted = list(tokens)
    positions: list[int] = []
    index = subcommand_index + 1
    while index < len(redacted):
        token = redacted[index]
        if token == "-t":
            index += 2
            continue
        if token.startswith("-") and len(token) > 1:
            index += 1
            continue
        positions.append(index)
        index += 1

    if len(positions) >= 2:
        redacted[positions[-1]] = REDACTED
    return redacted


def object_extra(
    subcommand: str,
    *,
    session: str | None = None,
    window: str | None = None,
    pane: str | None = None,
    target: str | int | None = None,
) -> dict[str, str]:
    """Build the ``extra`` mapping for a tmux object lifecycle record.

    Keeps the schema's two invariants in one place: every value is a ``str``,
    and a key absent from tmux is absent from the record rather than ``None``.

    Parameters
    ----------
    subcommand : str
        tmux subcommand the operation ran, e.g. ``"kill-pane"``.
    session : str, optional
        Session name.
    window : str, optional
        Window name or index.
    pane : str, optional
        Pane identifier.
    target : str | int, optional
        tmux target specifier the operation addressed.

    Returns
    -------
    dict[str, str]
        Mapping suitable for a logger's ``extra`` argument.

    Examples
    --------
    >>> object_extra("kill-pane", pane="%1", target="%1")
    {'tmux_subcommand': 'kill-pane', 'tmux_pane': '%1', 'tmux_target': '%1'}

    Omitted context stays out of the record:

    >>> object_extra("kill-server")
    {'tmux_subcommand': 'kill-server'}

    Non-string targets are coerced, so a formatter never sees an ``int``:

    >>> object_extra("kill-window", target=3)["tmux_target"]
    '3'
    """
    extra = {"tmux_subcommand": subcommand}
    for key, value in (
        ("tmux_session", session),
        ("tmux_window", window),
        ("tmux_pane", pane),
        ("tmux_target", target),
    ):
        if value is not None:
            extra[key] = str(value)
    return extra
