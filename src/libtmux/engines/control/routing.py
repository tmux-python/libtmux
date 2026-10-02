"""Which commands may ride the control connection.

A control client runs its commands on tmux's command queue one at a time, so a
command that waits holds every command behind it: forty ``run-shell`` calls of
0.3 s took 11.95 s on one connection and 0.36 s with ``-b``. Commands that wait
for a shell, a channel, or a person run in a subprocess instead.

The decision is pure: it reads an argv and answers yes or no.
"""

from __future__ import annotations

import typing as t

if t.TYPE_CHECKING:
    from collections.abc import Sequence

from libtmux.engines.base import is_command_separator

#: Commands that block the queue whatever their flags.
_ALWAYS = (
    "attach-session",
    "choose-buffer",
    "choose-client",
    "choose-tree",
    "command-prompt",
    "confirm-before",
    "display-menu",
    "display-panes",
    "display-popup",
    "kill-server",
    "wait-for",
)
#: Commands that block unless a flag detaches them: ``-b`` or ``-d``.
_UNLESS_FLAG = {
    "if-shell": "b",
    "new-session": "d",
    "run-shell": "b",
}
#: Flags whose value is the next token, per command.
_VALUED = {
    "if-shell": frozenset({"-c", "-t"}),
    "new-session": frozenset(
        {"-c", "-e", "-f", "-F", "-n", "-s", "-t", "-x", "-y"},
    ),
    "run-shell": frozenset({"-c", "-d", "-t"}),
}
#: Short names tmux accepts that are not a prefix of the full name.
_ALIASES = {
    "attach": "attach-session",
    "confirm": "confirm-before",
    "displayp": "display-panes",
    "if": "if-shell",
    "menu": "display-menu",
    "new": "new-session",
    "popup": "display-popup",
    "run": "run-shell",
}
_KNOWN = (*_ALWAYS, *_UNLESS_FLAG)


def _canonical(token: str) -> str | None:
    """Return the blocking-candidate command *token* names, if any."""
    if token in _ALIASES:
        return _ALIASES[token]
    if not token:
        return None
    matches = [name for name in _KNOWN if name.startswith(token)]
    # An ambiguous prefix is a tmux error either way; sending it to a
    # subprocess just returns that error unchanged.
    return matches[0] if matches else None


def _has_flag(rest: Sequence[str], flag: str, valued: frozenset[str]) -> bool:
    skip = False
    for token in rest:
        if skip:
            skip = False
            continue
        if not token.startswith("-") or token == "--":
            return False
        if token in valued:
            skip = True
            continue
        if flag in token[1:] and not token.startswith("--"):
            return True
    return False


def _segments(args: Sequence[str]) -> list[list[str]]:
    segments: list[list[str]] = [[]]
    for token in args:
        if is_command_separator(token):
            segments.append([])
        else:
            segments[-1].append(token)
    return segments


def blocks_queue(args: Sequence[str]) -> bool:
    """Return whether any command in *args* may block tmux's command queue.

    Parameters
    ----------
    args : sequence of str
        A request's argv, ``;``-separated by
        :class:`~libtmux.engines.base.CommandSeparator` when it holds several
        commands.

    Returns
    -------
    bool
        ``True`` when the request must not use the control connection.

    Examples
    --------
    >>> blocks_queue(("display-message", "-p", "hi"))
    False
    >>> blocks_queue(("run-shell", "sleep 1"))
    True
    >>> blocks_queue(("run-shell", "-b", "sleep 1"))
    False
    >>> blocks_queue(("wait-for", "ready"))
    True
    >>> blocks_queue(("new-session", "-d", "-s", "work"))
    False
    >>> blocks_queue(("new-session", "-s", "work"))
    True

    Aliases and prefixes count, and one blocking command taints a group:

    >>> blocks_queue(("run", "-t", "%1", "-b", "true"))
    False
    >>> blocks_queue(("wait", "ready"))
    True
    """
    for segment in _segments(args):
        if not segment:
            continue
        name = _canonical(segment[0])
        if name is None:
            continue
        if name in _ALWAYS:
            return True
        if not _has_flag(segment[1:], _UNLESS_FLAG[name], _VALUED[name]):
            return True
    return False
