"""Readers for the tmux variables exported into every pane's environment.

libtmux._internal.env
~~~~~~~~~~~~~~~~~~~~~

tmux exports two variables into the child environment of every pane it spawns:

``TMUX``
    ``"<socket_path>,<server_pid>,<session_id>"``. The session id is spelled
    *bare* -- ``47``, where libtmux spells the same session ``$47``.

``TMUX_PANE``
    ``"%N"`` -- the pane's id.

tmux also exports ``TMUX`` to the job children it spawns for ``run-shell`` and
``#()``, and those never get ``TMUX_PANE``. A ``#()`` job carries no session at
all, and its ``TMUX`` says so with a session id of ``-1``. So a process holding
a pane id always has a real session id beside it.

Both are frozen at spawn time and tmux never revises them. The moment a pane's
window is moved or linked into another session, the session id baked into
``TMUX`` is stale, while ``TMUX_PANE`` stays valid for the life of the pane.

libtmux therefore reads *only* the socket path out of ``TMUX`` and asks tmux
itself -- targeting ``TMUX_PANE`` -- for the pane's window and session. See
:meth:`libtmux.Pane.from_env`.
"""

from __future__ import annotations

import os
import pathlib
import typing as t

from libtmux import exc

TMUX: t.Final = "TMUX"
"""Environment variable tmux exports with ``socket_path,server_pid,session_id``."""

TMUX_PANE: t.Final = "TMUX_PANE"
"""Environment variable tmux exports with the pane's id, e.g. ``%3``."""


def resolve_env(env: t.Mapping[str, str] | None = None) -> t.Mapping[str, str]:
    """Return *env*, defaulting to the live process environment.

    Parameters
    ----------
    env : :class:`typing.Mapping`, optional
        Environment to read. Defaults to :data:`os.environ`.

    Returns
    -------
    :class:`typing.Mapping`
        The mapping to read tmux variables from.

    Examples
    --------
    >>> from libtmux._internal.env import resolve_env
    >>> resolve_env({"TMUX_PANE": "%1"})
    {'TMUX_PANE': '%1'}

    >>> resolve_env() is os.environ
    True
    """
    return os.environ if env is None else env


def socket_path_from_env(env: t.Mapping[str, str] | None = None) -> str:
    """Return the tmux socket path recorded in ``$TMUX``.

    ``$TMUX`` is ``"<socket_path>,<server_pid>,<session_id>"``. The pid and
    session id are integers, so any comma in the value belongs to the socket
    path -- split from the *right*.

    The pid and session id are deliberately discarded: both are frozen at pane
    spawn, and the session id goes stale as soon as the pane's window is moved
    between sessions.

    Parameters
    ----------
    env : :class:`typing.Mapping`, optional
        Environment to read. Defaults to :data:`os.environ`.

    Returns
    -------
    str
        Path of the tmux server's socket.

    Raises
    ------
    :exc:`~libtmux.exc.NotInsideTmux`
        When ``$TMUX`` is unset, empty, or not shaped like tmux's triple.

    Examples
    --------
    >>> from libtmux._internal.env import socket_path_from_env
    >>> socket_path_from_env({"TMUX": "/tmp/tmux-1000/default,84215,0"})
    '/tmp/tmux-1000/default'

    A comma in the socket path is safe, because the split runs from the right:

    >>> socket_path_from_env({"TMUX": "/tmp/od,d/sock,84215,3"})
    '/tmp/od,d/sock'

    Outside tmux there is nothing to read:

    >>> socket_path_from_env({})
    Traceback (most recent call last):
    ...
    libtmux.exc.NotInsideTmux: Not inside a tmux pane: $TMUX is unset or empty
    """
    raw = resolve_env(env).get(TMUX, "")
    if not raw:
        raise exc.NotInsideTmux(TMUX)

    parts = raw.rsplit(",", 2)
    if (
        len(parts) != 3
        or not parts[0]
        or not parts[1].isascii()
        or not parts[1].isdecimal()
        or int(parts[1]) <= 0
        or (
            parts[2] != "-1"
            and (
                not parts[2].removeprefix("$").isascii()
                or not parts[2].removeprefix("$").isdecimal()
            )
        )
    ):
        raise exc.NotInsideTmux(
            TMUX,
            reason="not '<socket_path>,<server_pid>,<session_id>'",
        )
    return parts[0]


def _absolute_socket_path(value: str, selector: str) -> str:
    """Validate a selected path without changing its spelling."""
    if "\0" in value or not pathlib.Path(value).is_absolute():
        msg = f"{selector} must be an absolute path without NUL"
        raise ValueError(msg)
    return value


def resolve_server_endpoint(
    socket_path: str | pathlib.Path | None,
    socket_name: str | None,
    env: dict[str, str],
) -> tuple[str, str | None]:
    """Capture an endpoint and its named-socket root in a private environment."""
    if socket_path is not None and socket_name is not None:
        msg = "socket_path and socket_name are mutually exclusive"
        raise ValueError(msg)
    if socket_path is not None:
        return _absolute_socket_path(str(socket_path), "socket_path"), None
    if socket_name is None:
        if path := env.get("LIBTMUX_SOCKET_PATH"):
            return _absolute_socket_path(path, "LIBTMUX_SOCKET_PATH"), None
        if name := env.get("LIBTMUX_SOCKET_NAME"):
            socket_name = name
        elif env.get(TMUX):
            return _absolute_socket_path(socket_path_from_env(env), TMUX), None
        else:
            socket_name = "default"
    if (
        not socket_name
        or socket_name in {".", ".."}
        or any(character in socket_name for character in ("/", "\\", "\0"))
    ):
        msg = "socket_name must be a nonempty leaf name without separators or NUL"
        raise ValueError(msg)
    root = _absolute_socket_path(env.get("TMUX_TMPDIR") or "/tmp", "TMUX_TMPDIR")
    env["TMUX_TMPDIR"] = root
    return str(pathlib.Path(root) / f"tmux-{os.getuid()}" / socket_name), socket_name


def pane_id_from_env(env: t.Mapping[str, str] | None = None) -> str:
    """Return the pane id recorded in ``$TMUX_PANE``.

    The ``%`` sigil is load-bearing: libtmux passes this id straight to tmux as
    a ``-t`` target, and tmux's ``cmd_find`` routes a target to its pane slot
    *by sigil*. A sigil-less value would be matched against session names
    instead, silently resolving to the wrong object.

    Parameters
    ----------
    env : :class:`typing.Mapping`, optional
        Environment to read. Defaults to :data:`os.environ`.

    Returns
    -------
    str
        The pane id, e.g. ``"%3"``.

    Raises
    ------
    :exc:`~libtmux.exc.NotInsideTmux`
        When ``$TMUX_PANE`` is unset, empty, or is not a ``%``-prefixed id.

    Examples
    --------
    >>> from libtmux._internal.env import pane_id_from_env
    >>> pane_id_from_env({"TMUX_PANE": "%3"})
    '%3'

    >>> pane_id_from_env({})
    Traceback (most recent call last):
    ...
    libtmux.exc.NotInsideTmux: Not inside a tmux pane: $TMUX_PANE is unset or empty

    >>> pane_id_from_env({"TMUX_PANE": "3"})
    Traceback (most recent call last):
    ...
    libtmux.exc.NotInsideTmux: Not inside a tmux pane: $TMUX_PANE is not a pane id...
    """
    pane_id = resolve_env(env).get(TMUX_PANE, "")
    if not pane_id:
        raise exc.NotInsideTmux(TMUX_PANE)
    if not pane_id.startswith("%"):
        raise exc.NotInsideTmux(
            TMUX_PANE,
            reason=f"not a pane id (expected '%N', got {pane_id!r})",
        )
    return pane_id
