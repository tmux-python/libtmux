"""Caller context: who launched this MCP server, read from its own environment.

A tmux ``-C`` control client resolves a no-target or relative target against its
*own* cursor pane, never the pane that launched the controlling process -- so the
caller pane is knowable only from the server process's environment. A process
spawned inside a tmux pane inherits ``TMUX_PANE`` (its ``%N`` id) and ``TMUX``
(``socket-path,server-pid,session-id``); those are fixed for the process
lifetime, so the curated tools can read them at call time and the adapter can
read them once for the server instructions -- both see the same launching pane.

Everything here is pure (no tmux call, no fastmcp): the whole point is to *avoid*
asking tmux, which would answer for the control client instead of the caller. A
pane id is unique only within one tmux server, so :func:`is_strict_caller`
socket-scopes the comparison rather than trusting a bare ``%N``.
"""

from __future__ import annotations

import os
import os.path
import typing as t
from dataclasses import dataclass

if t.TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclass(frozen=True)
class CallerContext:
    """The tmux pane/server that launched this MCP, parsed from the environment.

    Examples
    --------
    >>> env = {"TMUX_PANE": "%3", "TMUX": "/tmp/tmux-1000/default,42,2"}
    >>> c = CallerContext.from_env(env)
    >>> (c.pane_id, c.socket_path, c.session_id, c.in_tmux)
    ('%3', '/tmp/tmux-1000/default', '2', True)
    >>> CallerContext.from_env({}).in_tmux
    False
    >>> CallerContext.from_env({"TMUX": "garbage"}).socket_path is None
    True
    >>> CallerContext.from_env({"TMUX": "/tmp/a,b/sock,1,2"}).socket_path
    '/tmp/a,b/sock'
    """

    pane_id: str | None = None
    socket_path: str | None = None
    server_pid: str | None = None
    session_id: str | None = None
    in_tmux: bool = False

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> CallerContext:
        """Parse the caller context from *environ* (defaults to ``os.environ``).

        Degrades gracefully: a missing ``TMUX``/``TMUX_PANE`` yields a context
        with ``in_tmux=False``; a malformed ``TMUX`` (not three comma fields)
        leaves the socket/pid/session ``None`` but still records the pane. The
        ``pid`` and ``session`` are the final two comma fields, so the value is
        split from the right -- a socket path may itself contain a comma.
        """
        env = os.environ if environ is None else environ
        pane = env.get("TMUX_PANE") or None
        raw = env.get("TMUX") or None
        socket_path = server_pid = session_id = None
        if raw is not None:
            parts = raw.rsplit(",", 2)
            if len(parts) == 3:
                socket_path, server_pid, session_id = parts
        return cls(
            pane_id=pane,
            socket_path=socket_path,
            server_pid=server_pid,
            session_id=session_id,
            in_tmux=pane is not None,
        )


def _scan_flag(args: Sequence[str], flag: str) -> str | None:
    """Read a tmux connection flag's value (joined ``-Sx`` or separated ``-S x``)."""
    for index, arg in enumerate(args):
        if arg == flag and index + 1 < len(args):
            return args[index + 1] or None
        if arg.startswith(flag) and len(arg) > len(flag):
            return arg[len(flag) :]
    return None


def engine_socket(engine: t.Any) -> str | None:
    """Return the socket selector an engine targets (``-S`` path / ``-L`` name).

    Prefers an explicit ``-S`` path (the most precise selector) over a ``-L``
    name. ``None`` means the engine uses the ambient ``$TMUX`` server -- the same
    server as a caller running inside tmux.

    Examples
    --------
    >>> import types
    >>> engine_socket(types.SimpleNamespace(server_args=("-Lwork",)))
    'work'
    >>> engine_socket(types.SimpleNamespace(server_args=("-S", "/tmp/x")))
    '/tmp/x'
    >>> engine_socket(types.SimpleNamespace(server_args=())) is None
    True
    """
    args = tuple(getattr(engine, "server_args", ()) or ())
    path = _scan_flag(args, "-S")
    if path is not None:
        return path
    return _scan_flag(args, "-L")


def socket_matches(socket: str | None, caller: CallerContext) -> bool:
    """Whether an engine *socket* selector denotes the caller's tmux server.

    A default engine (``socket is None``) talks to the ambient ``$TMUX`` server,
    which is the caller's server when the caller is inside tmux *and* its socket
    is known. A ``-S`` path is realpath-compared; a ``-L`` name is resolved to its
    per-user socket path (honouring ``$TMUX_TMPDIR``) and realpath-compared, so a
    bare name cannot collide with an unrelated socket's basename.

    Examples
    --------
    >>> caller = CallerContext.from_env({"TMUX_PANE": "%1", "TMUX": "/tmp/s,1,2"})
    >>> socket_matches(None, caller)
    True
    >>> socket_matches("/tmp/s", caller)
    True
    >>> socket_matches("/tmp/other", caller)
    False
    """
    if socket is None:
        return caller.in_tmux and caller.socket_path is not None
    if caller.socket_path is None:
        return False
    if "/" in socket:
        return os.path.realpath(socket) == os.path.realpath(caller.socket_path)
    tmpdir = os.environ.get("TMUX_TMPDIR") or "/tmp"
    expected = f"{tmpdir}/tmux-{os.getuid()}/{socket}"
    return os.path.realpath(expected) == os.path.realpath(caller.socket_path)


def is_strict_caller(
    pane_id: str | None,
    socket: str | None,
    caller: CallerContext,
) -> bool:
    """Whether *pane_id* on an engine bound to *socket* is the caller's own pane.

    Strict: requires pane-id equality *and* a confirmed socket match, since a
    pane id is unique only within one tmux server. Bare pane-id equality is
    rejected to avoid a cross-server false positive.

    Examples
    --------
    >>> caller = CallerContext.from_env(
    ...     {"TMUX_PANE": "%3", "TMUX": "/tmp/tmux-1000/default,42,2"}
    ... )
    >>> is_strict_caller("%3", None, caller)
    True
    >>> is_strict_caller("%9", None, caller)
    False
    >>> is_strict_caller("%3", "/tmp/tmux-1000/other", caller)
    False
    """
    if not caller.in_tmux or caller.pane_id is None or pane_id != caller.pane_id:
        return False
    return socket_matches(socket, caller)
