"""Structured logging context for :mod:`libtmux`.

Pure helpers that turn a tmux command line, or a tmux object's identity, into
the ``extra`` mapping libtmux attaches to its log records. Nothing here runs
tmux or touches a logger, so the record schema is testable without a server.
"""

from __future__ import annotations

import os
import shlex
import typing as t

if t.TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = (
    "REDACTED",
    "CommandContext",
    "describe_command",
    "object_extra",
    "redact_output",
)

REDACTED = "REDACTED"
"""Placeholder substituted for environment values in logged command lines.

Chosen to survive quoting untouched, so quoting in a logged command line
still marks a genuinely quoted argument.
"""

_COMMAND_CAP = 16384
"""Practical rendered-character cap derived from tmux's message ceiling.

Quoting and UTF-8 mean this is not an exact model of tmux's transport bytes.
"""

_CONTROL_CHARS = (
    frozenset(chr(code) for code in range(0x20))
    | frozenset(chr(code) for code in range(0x7F, 0xA0))
    | {"\u2028", "\u2029"}
)

_CONTROL_ESCAPES = {
    "\a": r"\a",
    "\b": r"\b",
    "\t": r"\t",
    "\n": r"\n",
    "\v": r"\v",
    "\f": r"\f",
    "\r": r"\r",
    "\x1b": r"\e",
}

_VALUE_FLAGS = frozenset("cfLST")
"""tmux global flags that consume the argument after them.

Mirrors the ``getopt`` string in tmux's ``tmux.c`` (``2c:CDdf:hlL:NqS:T:uUvV``).
Every other global flag is a boolean and may be bundled, as in ``-2q``.
"""

_CANONICAL_SUBCOMMANDS = {
    "new": "new-session",
    "neww": "new-window",
    "newp": "new-pane",
    "popup": "display-popup",
    "respawnp": "respawn-pane",
    "respawnw": "respawn-window",
    "splitw": "split-window",
    "split-pane": "split-window",
    "splitp": "split-window",
    "setenv": "set-environment",
    "showenv": "show-environment",
    "capturep": "capture-pane",
    "setb": "set-buffer",
    "saveb": "save-buffer",
    "showb": "show-buffer",
    "lsb": "list-buffers",
    "showmsgs": "show-messages",
    "server-info": "show-messages",
    "info": "show-messages",
    "showphist": "show-prompt-history",
}
"""Relevant tmux aliases mapped to the policy command they execute."""

_ENV_SUBCOMMANDS = frozenset(
    {
        "new-session",
        "new-window",
        "new-pane",
        "display-popup",
        "respawn-pane",
        "respawn-window",
        "split-window",
    },
)
"""Subcommands whose ``-e`` carries a ``NAME=VALUE`` pair.

``select-pane -e`` and ``copy-mode -e`` are booleans, so a bare ``-e`` is never
read as an environment pair.
"""

_ENV_BOOLEAN_FLAGS = {
    "new-session": frozenset("AdDEPX"),
    "new-window": frozenset("abdkPS"),
    "new-pane": frozenset("bdEfhIkLPvZ"),
    "display-popup": frozenset("BCEkN"),
    "respawn-pane": frozenset("k"),
    "respawn-window": frozenset("k"),
    "split-window": frozenset("bdEfhIkPvZ"),
}
"""Boolean flags that tmux permits before bundled value-taking ``-e``."""

_SETENV_SUBCOMMANDS = frozenset({"set-environment"})
"""Subcommands shaped ``[-Fhgru] [-t target] variable [value]``."""

_ENV_OUTPUT_SUBCOMMANDS = frozenset({"show-environment"})
"""Subcommands whose stdout reports ``NAME=VALUE`` for environment variables."""

_BUFFER_INPUT_SUBCOMMANDS = frozenset({"set-buffer"})
"""Subcommands whose positional data is caller-provided buffer content."""

_CONTENT_SUBCOMMANDS = frozenset(
    {
        "capture-pane",
        "list-buffers",
        "save-buffer",
        "show-buffer",
        "show-messages",
        "show-prompt-history",
    },
)
"""Subcommands whose stdout is terminal or buffer content rather than control data.

Their output is whatever happened to be on a screen or in a paste buffer, and it
already reaches the caller as a return value, so a record reports how much came
back instead of what it was."""

_ENVIRONMENT_POLICY = "environment"
_SETENV_POLICY = "set-environment"
_BUFFER_INPUT_POLICY = "set-buffer"
_SENSITIVE_OUTPUT_POLICY = "sensitive-output"

_POLICY_BY_COMMAND = {
    **dict.fromkeys(_ENV_SUBCOMMANDS, _ENVIRONMENT_POLICY),
    **dict.fromkeys(_SETENV_SUBCOMMANDS, _SETENV_POLICY),
    **dict.fromkeys(_BUFFER_INPUT_SUBCOMMANDS, _BUFFER_INPUT_POLICY),
    **dict.fromkeys(_ENV_OUTPUT_SUBCOMMANDS, _SENSITIVE_OUTPUT_POLICY),
    **dict.fromkeys(_CONTENT_SUBCOMMANDS, _SENSITIVE_OUTPUT_POLICY),
}
"""Canonical commands grouped by the log-safety policy they share."""


def _quote(token: str) -> str:
    r"""Quote one argument for a log record, keeping control characters out.

    A caller controls much of what reaches a tmux command line — the keys
    :meth:`Pane.send_keys` sends, a start directory, a window command. A
    newline among them would end the log line early and let the remainder pose
    as a record of its own, so a token carrying control characters is rendered
    with shell ANSI-C quoting. The result remains pasteable for ordinary tmux
    arguments, but the log itself stays on one line.

    Examples
    --------
    >>> _quote("plain")
    'plain'

    >>> _quote("has space")
    "'has space'"

    A newline cannot break out of the record:

    >>> _quote("echo hi\nCRITICAL forged")
    "$'echo hi\\nCRITICAL forged'"

    Neither can an escape sequence reach the terminal reading the log:

    >>> _quote("\x1b[31mred")
    "$'\\e[31mred'"
    """
    if not _CONTROL_CHARS.intersection(token):
        return shlex.quote(token)

    escaped = []
    for char in token:
        if char in {"\\", "'"}:
            escaped.append("\\" + char)
        elif char in _CONTROL_ESCAPES:
            escaped.append(_CONTROL_ESCAPES[char])
        elif char in _CONTROL_CHARS:
            codepoint = ord(char)
            if codepoint <= 0x7F:
                escaped.append(f"\\x{codepoint:02x}")
            elif codepoint <= 0xFFFF:
                escaped.append(f"\\u{codepoint:04x}")
            else:
                escaped.append(f"\\U{codepoint:08x}")
        else:
            escaped.append(char)
    return "$'" + "".join(escaped) + "'"


def _canonical_subcommand(subcommand: str | None) -> str | None:
    """Return the command name used for logging policy decisions.

    Examples
    --------
    >>> _canonical_subcommand("new")
    'new-session'

    >>> _canonical_subcommand("list-sessions")
    'list-sessions'
    """
    if subcommand is None:
        return None
    return _CANONICAL_SUBCOMMANDS.get(subcommand, subcommand)


def _policy_for_subcommand(subcommand: str | None) -> str | None:
    """Return the safety policy for an exact command or tmux abbreviation.

    A prefix is safe to classify when every protected command it matches uses
    the same policy. Prefixes spanning incompatible argument grammars remain
    unclassified.

    Examples
    --------
    >>> _policy_for_subcommand("new-")
    'environment'

    >>> _policy_for_subcommand("set-") is None
    True
    """
    canonical_subcommand = _canonical_subcommand(subcommand)
    if canonical_subcommand is None:
        return None
    exact_policy = _POLICY_BY_COMMAND.get(canonical_subcommand)
    if exact_policy is not None:
        return exact_policy

    policies = {
        policy
        for command, policy in _POLICY_BY_COMMAND.items()
        if command.startswith(canonical_subcommand)
    }
    return policies.pop() if len(policies) == 1 else None


def _safe_scalar(value: str | None) -> str | None:
    r"""Quote control characters while preserving ordinary field values.

    Examples
    --------
    >>> _safe_scalar("server")
    'server'

    >>> _safe_scalar("safe\nERROR forged")
    "$'safe\\nERROR forged'"
    """
    if value is None or not _CONTROL_CHARS.intersection(value):
        return value
    return _quote(value)


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
        :data:`REDACTED`. A line longer than :data:`_COMMAND_CAP` is shortened
        and ends in an ellipsis.
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

    >>> describe_command(["tmux", "-Lmysock", "new-session", "-d"]).subcommand
    'new-session'

    >>> describe_command(["tmux", "-Lmysock", "new-session", "-d"]).socket
    'mysock'

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
    """
    tokens = [str(arg) for arg in argv]
    subcommand: str | None = None
    socket_label: str | None = None
    socket_path: str | None = None
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
            if flag == "L":
                socket_label = value
            elif flag == "S":
                socket_path = value
            takes_next_token = not joined_value
            break
        index += 2 if takes_next_token else 1

    command = " ".join(
        _quote(token) for token in _redact(tokens, subcommand, subcommand_index)
    )
    return CommandContext(
        subcommand=subcommand,
        socket=_safe_scalar(socket_path if socket_path is not None else socket_label),
        command=(
            command
            if len(command) <= _COMMAND_CAP
            else command[: _COMMAND_CAP - 1] + "\N{HORIZONTAL ELLIPSIS}"
        ),
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
    policy = _policy_for_subcommand(subcommand)
    if policy == _SETENV_POLICY:
        return _redact_set_environment(tokens, subcommand_index)
    if policy == _BUFFER_INPUT_POLICY:
        return _redact_set_buffer(tokens, subcommand_index)

    redacted = list(tokens)
    separated_pairs = policy == _ENVIRONMENT_POLICY
    canonical_subcommand = _canonical_subcommand(subcommand)
    matching_flags = [
        flags
        for command, flags in _ENV_BOOLEAN_FLAGS.items()
        if canonical_subcommand is not None
        and (
            command == canonical_subcommand or command.startswith(canonical_subcommand)
        )
    ]
    boolean_flags = frozenset().union(*matching_flags)
    index = subcommand_index + 1
    while index < len(redacted):
        token = redacted[index]
        if separated_pairs and token.startswith("-"):
            options = token[1:]
            for position, flag in enumerate(options):
                if flag == "e":
                    attached = options[position + 1 :]
                    if "=" in attached:
                        name = attached.split("=", 1)[0]
                        redacted[index] = f"-{options[: position + 1]}{name}={REDACTED}"
                    elif not attached and index + 1 < len(redacted):
                        following = redacted[index + 1]
                        if "=" in following:
                            redacted[index + 1] = (
                                f"{following.split('=', 1)[0]}={REDACTED}"
                            )
                        index += 1
                    break
                if flag not in boolean_flags:
                    break
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
    index = subcommand_index + 1
    while index < len(redacted):
        token = redacted[index]
        if token == "--":
            index += 1
            break
        if token.startswith("-") and len(token) > 1:
            takes_next = False
            valid_option = True
            for position, flag in enumerate(token[1:]):
                if flag == "t":
                    takes_next = position == len(token) - 2
                    break
                if flag not in "Fhgru":
                    valid_option = False
                    break
            if valid_option:
                index += 2 if takes_next else 1
                continue
        break

    if index + 1 < len(redacted):
        redacted[index + 1] = REDACTED
    return redacted


def _redact_set_buffer(tokens: list[str], subcommand_index: int) -> list[str]:
    """Return ``tokens`` with ``set-buffer`` data replaced.

    Examples
    --------
    >>> _redact_set_buffer(["tmux", "set-buffer", "-b", "name", "data"], 1)
    ['tmux', 'set-buffer', '-b', 'name', 'REDACTED']

    A command that only selects a buffer has no data to redact:

    >>> _redact_set_buffer(["tmux", "set-buffer", "-b", "name"], 1)
    ['tmux', 'set-buffer', '-b', 'name']
    """
    redacted = list(tokens)
    index = subcommand_index + 1
    while index < len(redacted):
        token = redacted[index]
        if token == "--":
            index += 1
            break
        if token.startswith("-") and len(token) > 1:
            takes_next = False
            valid_option = True
            for position, flag in enumerate(token[1:]):
                if flag in "bnt":
                    takes_next = position == len(token) - 2
                    break
                if flag not in "aw":
                    valid_option = False
                    break
            if valid_option:
                index += 2 if takes_next else 1
                continue
        break

    if index < len(redacted):
        redacted[index] = REDACTED
    return redacted


def redact_output(subcommand: str | None, lines: list[str]) -> list[str]:
    """Hide values in output that reports environment variables.

    Redacting what libtmux sends is only half of it: ``show-environment`` hands
    the same values straight back on stdout, so
    :meth:`~libtmux.common.EnvironmentMixin.getenv` would log a secret that
    :meth:`~libtmux.common.EnvironmentMixin.set_environment` was careful not to.

    Parameters
    ----------
    subcommand : str | None
        tmux subcommand that produced ``lines``.
    lines : list[str]
        Output lines as tmux wrote them.

    Returns
    -------
    list[str]
        Safe lines for a log record. Sensitive command output is withheld.

    Examples
    --------
    >>> redact_output("show-environment", ["EDITOR=vim", "continued value"])
    []

    Terminal and buffer content is dropped rather than redacted — the caller
    already has it as a return value, and ``tmux_stdout_len`` still reports how
    much there was:

    >>> redact_output("capture-pane", ["$ whoami", "root"])
    []

    Output from anything else is left alone, so a debug record stays useful:

    >>> redact_output("list-sessions", ["mysession: 1 windows"])
    ['mysession: 1 windows']
    """
    # Dropping beats redacting: a subcommand in both sets returns content, and
    # content is withheld whole rather than pattern-matched.
    if _policy_for_subcommand(subcommand) == _SENSITIVE_OUTPUT_POLICY:
        return []
    return lines


def object_extra(
    subcommand: str,
    *,
    socket: str | os.PathLike[str] | None = None,
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
    socket : str | os.PathLike[str], optional
        Socket name or path identifying the tmux server.
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
    if socket is not None:
        extra["tmux_socket"] = t.cast(str, _safe_scalar(str(socket)))
    for key, value in (
        ("tmux_session", session),
        ("tmux_window", window),
        ("tmux_pane", pane),
        ("tmux_target", target),
    ):
        if value is not None:
            extra[key] = str(value)
    return extra
