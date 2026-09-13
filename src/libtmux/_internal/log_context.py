"""Structured logging context for tmux operations."""

from __future__ import annotations

import os
import shlex
from collections.abc import Sequence

_VALUE_FLAGS = frozenset("cfLST")
"""tmux global flags that consume a value."""

_BOOLEAN_FLAGS = frozenset("2CDdhlNquUvV")
"""tmux global flags that do not consume a value."""

LOG_OUTPUT_LINE_LIMIT = 100
"""Maximum output lines attached to one log record."""


def _safe_scalar(value: str) -> str:
    """Keep printable identities readable and escape control characters."""
    return value if value.isprintable() else ascii(value)


def _quote(value: str) -> str:
    """Quote a printable operation token or escape it as an ASCII literal."""
    return shlex.quote(value) if value.isprintable() else ascii(value)


def command_extra(argv: Sequence[str]) -> dict[str, str]:
    """Describe a tmux command and derive best-effort structured context."""
    tokens = [str(arg) for arg in argv]
    executable = tokens[0] if tokens else "tmux"
    subcommand: str | None = None
    socket_label: str | None = None
    socket_path: str | None = None

    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            index += 1
            if index < len(tokens):
                subcommand = tokens[index]
            break
        if not token.startswith("-") or token == "-":
            subcommand = token
            break

        known_option = True
        takes_next = False
        for position, flag in enumerate(token[1:]):
            if flag in _BOOLEAN_FLAGS:
                continue
            if flag not in _VALUE_FLAGS:
                known_option = False
                break
            attached = token[position + 2 :]
            value = attached or (tokens[index + 1] if index + 1 < len(tokens) else None)
            if flag == "L":
                socket_label = value
            elif flag == "S":
                socket_path = value
            takes_next = not attached
            break
        if not known_option:
            break
        index += 2 if takes_next else 1

    socket = socket_path if socket_path is not None else socket_label
    extra = {"tmux_cmd": " ".join(_quote(token) for token in (tokens or [executable]))}
    if subcommand is not None:
        extra["tmux_subcommand"] = _safe_scalar(subcommand)
    if socket is not None:
        extra["tmux_socket"] = _safe_scalar(socket)
    return extra


def object_extra(
    subcommand: str,
    *,
    socket: str | os.PathLike[str] | None = None,
    session: str | None = None,
    window: str | None = None,
    pane: str | None = None,
    target: str | int | None = None,
) -> dict[str, str]:
    """Build structured context for a tmux object lifecycle record."""
    extra = {"tmux_subcommand": subcommand}
    if socket is not None:
        extra["tmux_socket"] = _safe_scalar(str(socket))
    for key, value in (
        ("tmux_session", session),
        ("tmux_window", window),
        ("tmux_pane", pane),
        ("tmux_target", target),
    ):
        if value is not None:
            extra[key] = _safe_scalar(str(value))
    return extra
