"""Readers for the tmux variables libtmux takes its bearings from.

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

A third variable, ``TMUX_TMPDIR``, is read *by* tmux rather than exported by
it: it picks the directory tmux keeps its sockets in. See
:func:`resolve_socket_path`.
"""

from __future__ import annotations

import os
import pathlib
import sys
import typing as t

from libtmux import exc

if t.TYPE_CHECKING:
    from libtmux._internal.types import StrPath

TMUX: t.Final = "TMUX"
"""Environment variable tmux exports with ``socket_path,server_pid,session_id``."""

TMUX_PANE: t.Final = "TMUX_PANE"
"""Environment variable tmux exports with the pane's id, e.g. ``%3``."""

TMUX_TMPDIR: t.Final = "TMUX_TMPDIR"
"""Environment variable naming the directory tmux keeps its sockets in."""

DEFAULT_SOCKET_DIR: t.Final = "/tmp"
"""Socket directory tmux falls back to when ``$TMUX_TMPDIR`` is unset."""

DEFAULT_SOCKET_NAME: t.Final = "default"
"""Socket name tmux uses when neither ``-L`` nor ``-S`` was given."""

# ``sun_path`` in ``struct sockaddr_un`` is a fixed-size char array, and the
# stdlib publishes no constant for its size, so it is spelled out per platform.
# The size is part of each platform's frozen ABI: 104 bytes on the BSD-derived
# kernels (macOS, FreeBSD, OpenBSD, NetBSD), 108 on Linux and elsewhere. One
# byte of it is the NUL terminator. The test suite probes the running kernel to
# keep this honest, which reads better than bisecting for the limit at import
# time.
_SUN_PATH_SIZE: t.Final = (
    104 if sys.platform.startswith(("darwin", "freebsd", "openbsd", "netbsd")) else 108
)

SOCKET_PATH_MAX_BYTES: t.Final = _SUN_PATH_SIZE - 1
"""Bytes a tmux socket path may occupy on this platform."""


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


def resolve_socket_path(
    socket_name: str | None = None,
    env: t.Mapping[str, str] | None = None,
) -> pathlib.Path:
    """Resolve the socket path tmux uses for *socket_name*.

    tmux keeps its sockets in ``tmux-<euid>`` under ``$TMUX_TMPDIR``, falling
    back to ``/tmp`` when that is unset or empty. ``$TMPDIR`` is deliberately
    not consulted -- tmux does not consult it either. The socket directory is
    resolved through symlinks, as tmux resolves it before binding, so a
    symlinked ``$TMUX_TMPDIR`` yields the path tmux itself reports.

    A ``$TMUX_TMPDIR`` tmux cannot resolve falls back the same way. tmux takes
    the first of ``$TMUX_TMPDIR`` and ``/tmp`` that resolves, so a path that is
    not there -- or a broken symlink -- is never the one it binds, and
    measuring it would refuse a server tmux reaches without difficulty. A
    directory it resolves but cannot create ``tmux-<euid>`` under is an error
    from tmux, not a fallback.

    The path is *computed*, not observed: it says where tmux would put the
    socket, not that a daemon is listening there. Code holding a live
    :class:`~libtmux.Server` should ask tmux instead, with the
    ``#{socket_path}`` format.

    Parameters
    ----------
    socket_name : str, optional
        Socket name, as passed to tmux's ``-L``. Defaults to tmux's own
        default, ``"default"``.
    env : :class:`typing.Mapping`, optional
        Environment to read. Defaults to :data:`os.environ`.

    Returns
    -------
    :class:`pathlib.Path`
        Path tmux resolves the socket to.

    Examples
    --------
    >>> from libtmux._internal.env import resolve_socket_path
    >>> resolve_socket_path(env={})
    PosixPath('/tmp/tmux-.../default')

    >>> resolve_socket_path("mysocket", env={"TMUX_TMPDIR": "/usr"})
    PosixPath('/usr/tmux-.../mysocket')

    ``$TMPDIR`` is not a socket directory, so it changes nothing:

    >>> resolve_socket_path(env={"TMPDIR": "/var/folders/xy"})
    PosixPath('/tmp/tmux-.../default')

    Nor does a ``$TMUX_TMPDIR`` tmux cannot use, however long it is:

    >>> resolve_socket_path(env={"TMUX_TMPDIR": "/nonexistent-" + "d" * 200})
    PosixPath('/tmp/tmux-.../default')
    """
    tmpdir = resolve_env(env).get(TMUX_TMPDIR) or DEFAULT_SOCKET_DIR
    base = pathlib.Path(tmpdir)
    if not base.exists():
        base = pathlib.Path(DEFAULT_SOCKET_DIR)
    return (
        base.resolve() / f"tmux-{os.geteuid()}" / (socket_name or DEFAULT_SOCKET_NAME)
    )


def check_socket_path_length(
    socket_path: StrPath,
    *,
    socket_name: str | None = None,
    env_var: str | None = None,
    env_value: str | None = None,
) -> None:
    """Raise if *socket_path* is too long to be a UNIX socket address.

    A tmux socket is a UNIX domain socket, so its path has to fit in
    :data:`SOCKET_PATH_MAX_BYTES` -- a filesystem that accepts the path says
    nothing about whether a socket can be bound at it. Length is counted in
    *bytes*, as the kernel counts it, so a non-ASCII path runs out sooner than
    its character count suggests.

    Parameters
    ----------
    socket_path : str or :class:`os.PathLike`
        Path to measure.
    socket_name : str, optional
        Socket name *socket_path* was resolved from, when it was resolved
        rather than passed in. Recorded on the exception so the message can say
        the length was inherited from ``$TMUX_TMPDIR``.
    env_var : str, optional
        Environment variable the socket directory came from, when one did.
        Recorded on the exception so the message can name it.
    env_value : str, optional
        What that variable held, so the caller can see what to shorten.

    Raises
    ------
    :exc:`~libtmux.exc.SocketPathTooLong`
        When *socket_path* exceeds :data:`SOCKET_PATH_MAX_BYTES` bytes.

    Examples
    --------
    >>> from libtmux._internal.env import (
    ...     check_socket_path_length,
    ...     SOCKET_PATH_MAX_BYTES,
    ... )
    >>> check_socket_path_length("/tmp/tmux-1000/default")

    >>> try:
    ...     check_socket_path_length("/tmp/" + "d" * 200 + "/sock")
    ... except exc.SocketPathTooLong as e:
    ...     (e.length, e.limit == SOCKET_PATH_MAX_BYTES)
    (210, True)

    A name that resolves somewhere too deep reports the name too. The path is
    measured as given -- whether tmux would really bind there is settled by
    :func:`resolve_socket_path` before this is called:

    >>> deep = pathlib.Path("/tmp/" + "d" * 200) / "tmux-1000" / "dev"
    >>> try:
    ...     check_socket_path_length(deep, socket_name="dev")
    ... except exc.SocketPathTooLong as e:
    ...     e.socket_name
    'dev'
    """
    if len(os.fsencode(socket_path)) > SOCKET_PATH_MAX_BYTES:
        raise exc.SocketPathTooLong(
            socket_path,
            SOCKET_PATH_MAX_BYTES,
            socket_name=socket_name,
            env_var=env_var,
            env_value=env_value,
        )


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
    if len(parts) != 3 or not parts[0]:
        raise exc.NotInsideTmux(
            TMUX,
            reason="not '<socket_path>,<server_pid>,<session_id>'",
        )
    return parts[0]


def resolve_ambient_socket_path(env: t.Mapping[str, str] | None = None) -> pathlib.Path:
    """Resolve the socket a *bare* tmux invocation talks to, in tmux's own order.

    A tmux client given no ``-L`` or ``-S`` prefers ``$TMUX`` -- the socket of
    the pane it is running inside -- and only falls back to computing a path
    under ``$TMUX_TMPDIR`` when there is no pane. Measured against tmux 3.7b: a
    bare client with ``$TMUX`` set connects even when ``$TMUX_TMPDIR`` names a
    directory far too deep to bind, because it never looks there.

    That order only holds for the bare client. Passing ``-L`` sends tmux to
    ``$TMUX_TMPDIR`` regardless of ``$TMUX``, so a named socket resolves through
    :func:`resolve_socket_path` instead.

    Parameters
    ----------
    env : :class:`typing.Mapping`, optional
        Environment to read. Defaults to :data:`os.environ`.

    Returns
    -------
    :class:`pathlib.Path`
        Socket path a bare tmux client would use.

    Examples
    --------
    >>> from libtmux._internal.env import resolve_ambient_socket_path

    Inside a pane, ``$TMUX`` names the socket outright:

    >>> resolve_ambient_socket_path({"TMUX": "/tmp/tmux-1000/default,8421,0"})
    PosixPath('/tmp/tmux-1000/default')

    ``$TMUX_TMPDIR`` is not consulted when there is a pane to inherit from:

    >>> resolve_ambient_socket_path(
    ...     {"TMUX": "/tmp/sock,8421,0", "TMUX_TMPDIR": "/nowhere"}
    ... )
    PosixPath('/tmp/sock')

    Outside tmux it falls back to the computed path:

    >>> resolve_ambient_socket_path({})
    PosixPath('/tmp/tmux-.../default')
    """
    try:
        return pathlib.Path(socket_path_from_env(env))
    except exc.NotInsideTmux:
        return resolve_socket_path(env=env)


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
