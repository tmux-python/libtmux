"""Parse and normalize arguments passed directly to the tmux executable."""

from __future__ import annotations

import typing as t

from libtmux.engines.base import CommandSeparator, is_command_separator


class DirectArgv(t.NamedTuple):
    """Tmux arguments split at the client-option boundary.

    Attributes
    ----------
    global_args : tuple[str, ...]
        Client-global options and their values.
    command_argv : tuple[str | CommandSeparator, ...]
        Command names, flags, data, and explicit separators.
    """

    global_args: tuple[str, ...]
    command_argv: tuple[str | CommandSeparator, ...]


class ClientOption(t.NamedTuple):
    """One parsed tmux client-global option.

    Attributes
    ----------
    name : str
        Single-character option name without ``-``.
    value : str or None
        Attached or separate value for value-taking options.
    """

    name: str
    value: str | None


_CLIENT_OPTION_VALUE_CHARACTERS = frozenset("cfLST")
_CLIENT_FLAG_CHARACTERS = frozenset("2CDdhlNquUvV")


def _scan_client_prefix(
    raw_args: tuple[object, ...],
) -> tuple[int, tuple[ClientOption, ...]]:
    """Return the client-prefix boundary and its normalized options."""
    if any("\0" in str(arg) for arg in raw_args):
        msg = "tmux command arguments cannot contain NUL"
        raise ValueError(msg)
    options: list[ClientOption] = []
    index = 0
    while index < len(raw_args):
        arg = raw_args[index]
        if type(arg) is CommandSeparator:
            break
        token = str(arg)
        if "\0" in token:
            msg = "tmux command arguments cannot contain NUL"
            raise ValueError(msg)
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
            if option in _CLIENT_FLAG_CHARACTERS:
                options.append(ClientOption(option, None))
                position += 1
                continue
            if option in _CLIENT_OPTION_VALUE_CHARACTERS:
                attached = cluster[position + 1 :]
                if attached:
                    value: str | None = attached
                elif index + 1 < len(raw_args):
                    index += 1
                    value = str(raw_args[index])
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
    """Separate tmux client-global options from command arguments.

    Parameters
    ----------
    args : iterable[object]
        Arguments passed after the tmux executable.

    Returns
    -------
    DirectArgv
        Client-global prefix and command region.

    Examples
    --------
    >>> parsed = split_direct_argv(("-L", "socket", "display-message", ";"))
    >>> parsed.global_args
    ('-L', 'socket')
    >>> parsed.command_argv
    ('display-message', ';')
    """
    raw_args = tuple(args)
    command_start, _options = _scan_client_prefix(raw_args)

    global_args = tuple(str(arg) for arg in raw_args[:command_start])
    command_argv = tuple(
        arg if type(arg) is CommandSeparator else str(arg)
        for arg in raw_args[command_start:]
    )
    if any("\0" in str(arg) for arg in command_argv):
        msg = "tmux command arguments cannot contain NUL"
        raise ValueError(msg)
    if any(
        type(arg) is CommandSeparator and not is_command_separator(arg)
        for arg in command_argv
    ):
        msg = "a command separator must be exactly ';'"
        raise ValueError(msg)
    return DirectArgv(global_args=global_args, command_argv=command_argv)


def parse_client_options(args: t.Iterable[object]) -> tuple[ClientOption, ...]:
    """Parse normalized options from the leading tmux client argv region.

    Parameters
    ----------
    args : iterable[object]
        Arguments passed after the tmux executable.

    Returns
    -------
    tuple[ClientOption, ...]
        Options in command-line order, with clusters and values expanded.

    Examples
    --------
    >>> options = parse_client_options(("-uqLwork", "list-sessions"))
    >>> [(option.name, option.value) for option in options]
    [('u', None), ('q', None), ('L', 'work')]
    >>> parse_client_options(("-f", "/tmp/tmux.conf", "list-sessions"))[-1]
    ClientOption(name='f', value='/tmp/tmux.conf')
    """
    _boundary, options = _scan_client_prefix(tuple(args))
    return options


def encode_command_argv(args: t.Iterable[object]) -> tuple[str, ...]:
    r"""Encode argv already known to be in tmux's command parser region.

    Parameters
    ----------
    args : iterable[object]
        Command names, flags, values, and typed separators.

    Returns
    -------
    tuple[str, ...]
        Command argv with literal suffix semicolons protected.

    Examples
    --------
    >>> encode_command_argv(("-L", "value;", CommandSeparator(";")))
    ('-L', 'value\\;', ';')
    """
    command_argv = tuple(
        arg if type(arg) is CommandSeparator else str(arg) for arg in args
    )
    if any("\0" in str(arg) for arg in command_argv):
        msg = "tmux command arguments cannot contain NUL"
        raise ValueError(msg)
    if any(
        type(arg) is CommandSeparator and not is_command_separator(arg)
        for arg in command_argv
    ):
        msg = "a command separator must be exactly ';'"
        raise ValueError(msg)

    encoded: list[str] = []
    for arg in command_argv:
        if is_command_separator(arg):
            encoded.append(str.__str__(arg))
        elif arg.endswith(";") and not arg.endswith(r"\;"):
            encoded.append(f"{arg[:-1]}\\;")
        else:
            encoded.append(arg)
    return tuple(encoded)


def encode_direct_argv(args: t.Iterable[object]) -> tuple[str, ...]:
    r"""Render direct tmux argv with untyped trailing semicolons as data.

    An ordinary string ending in a bare semicolon receives the tmux-level
    escape needed to keep it literal. Existing ``\;`` suffixes are preserved,
    while a :class:`~libtmux.engines.base.CommandSeparator` renders as command
    structure. Client-global option values remain unchanged because tmux
    removes them before parsing command separators.

    Parameters
    ----------
    args : iterable[object]
        Arguments passed after the tmux executable.

    Returns
    -------
    tuple[str, ...]
        Normalized subprocess arguments.

    Examples
    --------
    >>> encode_direct_argv(("-Lsocket;", "display-message", "value;"))
    ('-Lsocket;', 'display-message', 'value\\;')
    >>> encode_direct_argv(("display-message", CommandSeparator(";")))
    ('display-message', ';')
    >>> encode_direct_argv(("display-message", r"already\;"))
    ('display-message', 'already\\;')
    """
    direct = split_direct_argv(args)
    return (*direct.global_args, *encode_command_argv(direct.command_argv))
