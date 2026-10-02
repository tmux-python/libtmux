"""Masking of secrets in the tmux argv that libtmux logs.

Lives outside :mod:`libtmux.common` so the engine layer, which forks every
tmux client, can use the same redactor as :class:`~libtmux.common.tmux_cmd`
without importing it. :mod:`libtmux.common` re-exports the public names.
"""

from __future__ import annotations

import shlex
import typing as t

if t.TYPE_CHECKING:
    from collections.abc import Callable, Sequence

_REDACTED = "***"

_GLOBAL_FLAGS_WITH_VALUE = frozenset({"-c", "-f", "-L", "-S", "-T"})
_ENV_FLAG_SUBCOMMANDS = frozenset(
    {
        "new-session",
        "new",
        "new-window",
        "neww",
        "new-pane",
        "split-window",
        "splitw",
        "respawn-pane",
        "respawnp",
        "respawn-window",
        "respawnw",
    },
)
_SEND_KEYS_FLAGS_WITH_VALUE = frozenset({"-c", "-N", "-t"})


def _subcommand_index(argv: Sequence[str]) -> int | None:
    """Return where the tmux subcommand sits in *argv*, or ``None``."""
    i = 1  # argv[0] is the tmux binary
    while i < len(argv):
        arg = argv[i]
        if not arg.startswith("-"):
            return i
        i += 2 if arg in _GLOBAL_FLAGS_WITH_VALUE else 1
    return None


def redact_env_values(argv: Sequence[str]) -> list[str]:
    """Mask environment values in a tmux argv, keeping the variable names.

    Covers ``-e NAME=value`` on the commands that take it, and the value of
    ``set-environment``. This is the default for the argv libtmux logs.

    Parameters
    ----------
    argv : sequence of str
        Full command line, with the tmux binary first.

    Returns
    -------
    list of str
        A copy of *argv*; *argv* itself is not modified.

    Examples
    --------
    >>> redact_env_values(["tmux", "new-window", "-eTOKEN=hunter2", "-d"])
    ['tmux', 'new-window', '-eTOKEN=***', '-d']

    >>> redact_env_values(["tmux", "split-window", "-e", "TOKEN=hunter2"])
    ['tmux', 'split-window', '-e', 'TOKEN=***']

    >>> redact_env_values(["tmux", "set-environment", "-t", "$0", "TOKEN", "hunter2"])
    ['tmux', 'set-environment', '-t', '$0', 'TOKEN', '***']

    >>> redact_env_values(["tmux", "capture-pane", "-e", "-p"])
    ['tmux', 'capture-pane', '-e', '-p']
    """
    out = list(argv)
    sub = _subcommand_index(out)
    if sub is None:
        return out
    name = out[sub]
    if name in _ENV_FLAG_SUBCOMMANDS:
        i = sub + 1
        while i < len(out):
            if out[i] == "-e" and i + 1 < len(out):
                key, eq, _ = out[i + 1].partition("=")
                out[i + 1] = f"{key}={_REDACTED}" if eq else out[i + 1]
                i += 2
                continue
            if out[i].startswith("-e") and "=" in out[i]:
                key = out[i].partition("=")[0]
                out[i] = f"{key}={_REDACTED}"
            i += 1
    elif name in {"set-environment", "setenv"}:
        positional = [
            i
            for i in range(sub + 1, len(out))
            if not out[i].startswith("-") and out[i - 1] != "-t"
        ]
        if len(positional) >= 2:
            out[positional[1]] = _REDACTED
    return out


def redact_send_keys(argv: Sequence[str]) -> list[str]:
    """Mask the keys typed by ``send-keys`` in a tmux argv.

    Opt-in: text typed into a pane is what most people debug from, so
    libtmux logs it unless this is part of the redactor in use.

    Parameters
    ----------
    argv : sequence of str
        Full command line, with the tmux binary first.

    Returns
    -------
    list of str
        A copy of *argv*; *argv* itself is not modified.

    Examples
    --------
    >>> redact_send_keys(["tmux", "send-keys", "-t", "%1", "echo hunter2", "Enter"])
    ['tmux', 'send-keys', '-t', '%1', '***', '***']

    >>> redact_send_keys(["tmux", "new-window", "-d"])
    ['tmux', 'new-window', '-d']
    """
    out = list(argv)
    sub = _subcommand_index(out)
    if sub is None or out[sub] not in {"send-keys", "send"}:
        return out
    i = sub + 1
    only_keys = False
    while i < len(out):
        if only_keys or not out[i].startswith("-"):
            out[i] = _REDACTED
        elif out[i] == "--":
            only_keys = True
        elif out[i] in _SEND_KEYS_FLAGS_WITH_VALUE:
            i += 1
        i += 1
    return out


_argv_redactor: Callable[[Sequence[str]], Sequence[str]] = redact_env_values


def set_argv_redactor(
    redactor: Callable[[Sequence[str]], Sequence[str]] | None,
) -> None:
    """Choose how the tmux argv is masked before libtmux logs it.

    libtmux logs each command line at ``DEBUG`` (the ``tmux_cmd`` key on
    records from ``libtmux.common``). The list queries in ``libtmux.neo``
    carry only format strings and are not passed through. By default
    :func:`redact_env_values` masks environment values so a secret passed
    with ``environment=`` never reaches a log handler. Replace it to mask
    more, for example the text of :meth:`Pane.send_keys`. The real argv
    handed to tmux, and :attr:`tmux_cmd.cmd`, are unchanged.

    Process-wide: applies to every server in this process, and to every
    thread. Set it once at start-up.

    Parameters
    ----------
    redactor : callable or None
        Takes the full argv (tmux binary first) and returns the argv to
        log. ``None`` restores :func:`redact_env_values`. An exception
        raised by the redactor is not caught, so make it total.

    Examples
    --------
    >>> set_argv_redactor(lambda argv: redact_send_keys(redact_env_values(argv)))
    >>> set_argv_redactor(None)
    """
    global _argv_redactor
    _argv_redactor = redactor if redactor is not None else redact_env_values


def _redacted_argv(argv: Sequence[str]) -> tuple[str, ...]:
    """Return ``argv`` with the active redactor applied, as a tuple.

    Examples
    --------
    >>> _redacted_argv(["tmux", "new-window", "-eTOKEN=hunter2"])
    ('tmux', 'new-window', '-eTOKEN=***')
    """
    return tuple(_argv_redactor(argv))


def _loggable_cmd(argv: Sequence[str]) -> str:
    """Return the shell-quoted argv with the active redactor applied."""
    return shlex.join(_redacted_argv(argv))
