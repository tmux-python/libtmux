"""Wire-level tmux argv packing, token escaping, and limit checks."""

from __future__ import annotations

import typing as t

from libtmux import exc

# MAX_IMSGSIZE (16384) - IMSG_HEADER_SIZE (16) - sizeof(struct msg_command) (4).
MAX_PACKED_ARGV_BYTES: t.Final[int] = 16_364

# cmd_unpack_argv ceiling in tmux cmd.c.
MAX_PACKED_ARGV_COUNT: t.Final[int] = 1_000

_CLIENT_OPTION_VALUE_CHARS: t.Final[frozenset[str]] = frozenset("cfLST")
_CLIENT_FLAG_CHARS: t.Final[frozenset[str]] = frozenset("28CDdhlNquUvV")


class DirectArgv(t.NamedTuple):
    """Tmux CLI tokens split at the client ``getopt`` boundary.

    Attributes
    ----------
    client_args : tuple[str, ...]
        Leading client flags and values consumed before ``cmd_parse_from_arguments``.
    command_args : tuple[str, ...]
        Remaining subcommand and arguments parsed by ``cmd_parse_from_arguments``.
    """

    client_args: tuple[str, ...]
    command_args: tuple[str, ...]


class ClientOption(t.NamedTuple):
    """Normalized tmux client-level short option.

    Attributes
    ----------
    name : str
        Single-character option flag without leading ``-``.
    value : str or None
        Option value when the flag takes an argument, else ``None``.
    """

    name: str
    value: str | None


def _reject_nul(token: str) -> None:
    if "\x00" in token:
        msg = "tmux command arguments cannot contain NUL"
        raise ValueError(msg)


def _scan_client_prefix(
    raw_args: tuple[str, ...],
) -> tuple[int, tuple[ClientOption, ...]]:
    for token in raw_args:
        _reject_nul(token)
    options: list[ClientOption] = []
    index = 0
    while index < len(raw_args):
        token = raw_args[index]
        if token == "--":
            index += 1
            break
        if len(token) <= 1 or not token.startswith("-"):
            break

        option_start = len(options)
        is_client_option = True
        position = 0
        cluster = token[1:]
        while position < len(cluster):
            option = cluster[position]
            if option in _CLIENT_FLAG_CHARS:
                options.append(ClientOption(option, None))
                position += 1
                continue
            if option in _CLIENT_OPTION_VALUE_CHARS:
                attached = cluster[position + 1 :]
                if attached:
                    value: str | None = attached
                elif index + 1 < len(raw_args):
                    index += 1
                    value = raw_args[index]
                else:
                    value = None
                options.append(ClientOption(option, value))
                break
            is_client_option = False
            del options[option_start:]
            break
        if not is_client_option:
            break
        index += 1
    return index, tuple(options)


def split_direct_argv(args: t.Iterable[object]) -> DirectArgv:
    """Separate leading tmux client flags from the subcommand argv.

    Examples
    --------
    >>> from libtmux._internal.invocation import split_direct_argv
    >>> split_direct_argv(("-L", "work;", "display-message", "text;"))
    DirectArgv(client_args=('-L', 'work;'), command_args=('display-message', 'text;'))
    """
    str_args = tuple(str(arg) for arg in args)
    boundary, _options = _scan_client_prefix(str_args)
    return DirectArgv(
        client_args=str_args[:boundary],
        command_args=str_args[boundary:],
    )


def split_command_chain(
    command_args: tuple[str, ...],
) -> tuple[tuple[str, ...], ...]:
    r"""Split CLI command tokens on interior ``";"`` command separators.

    Preserves multi-command ``Server.cmd(..., ";", ...)`` sequences while
    keeping trailing ``";"`` arguments (such as ``send-keys -l ";"``) inside
    their command so :func:`escape_command_token` protects them as literal data.

    Examples
    --------
    >>> from libtmux._internal.invocation import split_command_chain
    >>> split_command_chain(("send-keys", "-R", ";", "clear-history"))
    (('send-keys', '-R'), ('clear-history',))
    >>> split_command_chain(("send-keys", "-l", ";"))
    (('send-keys', '-l', ';'),)
    """
    if not command_args:
        return ()
    commands: list[tuple[str, ...]] = []
    current: list[str] = []
    total = len(command_args)
    for index, token in enumerate(command_args):
        has_following_cmd = any(
            later != ";" for later in command_args[index + 1 : total]
        )
        if token == ";" and current and has_following_cmd:
            commands.append(tuple(current))
            current = []
        else:
            current.append(token)
    if current:
        commands.append(tuple(current))
    return tuple(commands)


def parse_client_options(args: t.Iterable[object]) -> tuple[ClientOption, ...]:
    """Parse normalized leading tmux client options.

    Examples
    --------
    >>> from libtmux._internal.invocation import parse_client_options
    >>> parse_client_options(("-uqLwork", "list-sessions"))[-1]
    ClientOption(name='L', value='work')
    """
    str_args = tuple(str(arg) for arg in args)
    _boundary, options = _scan_client_prefix(str_args)
    return options


def escape_command_token(token: str) -> str:
    r"""Escape trailing ``;`` on one command token so tmux keeps it as data.

    ``cmd_parse_from_arguments`` in tmux treats any argument ending in an
    unescaped ``;`` as a command boundary and strips one leading ``\`` from
    ``\;``. Already-escaped ``\;`` tokens are left intact so legacy workarounds
    are not double-escaped.

    Examples
    --------
    >>> from libtmux._internal.invocation import escape_command_token
    >>> escape_command_token("echo hi;")
    'echo hi\\;'
    >>> escape_command_token("echo hi\\;")
    'echo hi\\;'
    >>> escape_command_token("a;b")
    'a;b'
    """
    _reject_nul(token)
    if token.endswith(";") and not token.endswith(r"\;"):
        return f"{token[:-1]}\\;"
    return token


def check_packed_argv_limits(command_tokens: tuple[str, ...]) -> None:
    """Raise :exc:`~libtmux.exc.TmuxCommandTooLong` above ``MSG_COMMAND`` limits."""
    argc = len(command_tokens)
    packed_bytes = sum(
        len(tok.encode("utf-8", errors="surrogateescape")) + 1 for tok in command_tokens
    )
    if argc > MAX_PACKED_ARGV_COUNT or packed_bytes > MAX_PACKED_ARGV_BYTES:
        raise exc.TmuxCommandTooLong(
            packed_bytes=packed_bytes,
            argc=argc,
            max_bytes=MAX_PACKED_ARGV_BYTES,
            max_argc=MAX_PACKED_ARGV_COUNT,
        )


def flatten_commands(
    commands: tuple[tuple[str, ...], ...],
    *,
    check_imsg_limits: bool = True,
) -> tuple[str, ...]:
    r"""Flatten structured command tuples into an escaped CLI argv tail.

    Each command's data tokens pass through :func:`escape_command_token`; bare
    ``";"`` tokens are inserted only between distinct commands in *commands*.

    Examples
    --------
    >>> from libtmux._internal.invocation import flatten_commands
    >>> flatten_commands((("send-keys", "a;"), ("list-panes",)))
    ('send-keys', 'a\\;', ';', 'list-panes')
    """
    flat: list[str] = []
    for cmd_index, cmd in enumerate(commands):
        if not cmd:
            msg = "tmux command tuple cannot be empty"
            raise ValueError(msg)
        if cmd_index > 0:
            flat.append(";")
        flat.extend(escape_command_token(token) for token in cmd)
    result = tuple(flat)
    if check_imsg_limits and result:
        check_packed_argv_limits(result)
    return result


def escape_format_literal(value: str) -> str:
    """Escape ``#`` as ``##`` for tmux flags that expand format strings.

    Examples
    --------
    >>> from libtmux._internal.invocation import escape_format_literal
    >>> escape_format_literal("issue-#42")
    'issue-##42'
    """
    _reject_nul(value)
    return value.replace("#", "##")
