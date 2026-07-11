"""Caller context: who launched this MCP server, discovered from the environment.

A tmux ``-C`` control client resolves a no-target or relative target against its
*own* cursor pane, never the pane that launched the controlling process -- so the
caller pane is knowable only from the server process's environment, not by asking
tmux. A process spawned inside a tmux pane inherits ``TMUX_PANE`` (its ``%N``) and
``TMUX`` (``socket-path,server-pid,session-id``).

But real launchers strip that env: an agent harness may hold ``TMUX``/
``TMUX_PANE`` while the ``uv run`` child that became this server does not. So
:meth:`CallerContext.discover` layers the server's own env, an explicit override,
and a bounded same-uid ``/proc`` parent walk (:mod:`._proc`) to recover the pane.

Everything here is pure (no tmux call, no fastmcp). A pane id is unique only
within one tmux server, so identity is socket-scoped: :func:`is_strict_caller`
(realpath-only, for the ``is_caller`` annotation) and the fail-safe
:func:`socket_could_match` (true-when-uncertain, for destructive guards).
"""

from __future__ import annotations

import dataclasses
import os
import os.path
import pathlib
import typing as t
from dataclasses import dataclass

from libtmux.experimental.mcp.vocabulary._proc import (
    read_proc_environ,
    read_proc_ppid,
    read_proc_uid,
)

if t.TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence


@dataclass(frozen=True)
class CallerContext:
    """The tmux pane/server that launched this MCP, parsed from the environment.

    Examples
    --------
    >>> env = {"TMUX_PANE": "%3", "TMUX": "/tmp/tmux-1000/default,42,2"}
    >>> c = CallerContext.from_env(env)
    >>> (c.pane_id, c.socket_path, c.session_id, c.in_tmux, c.source)
    ('%3', '/tmp/tmux-1000/default', '2', True, 'process-env')
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
    source: str = "none"

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
            source="process-env" if pane is not None else "none",
        )

    @classmethod
    def discover(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        read_env: Callable[[int], Mapping[str, str] | None] = read_proc_environ,
        read_ppid: Callable[[int], int | None] = read_proc_ppid,
        read_uid: Callable[[int], int | None] = read_proc_uid,
        self_pid: int | None = None,
        self_uid: int | None = None,
        is_linux: bool | None = None,
        max_depth: int = 32,
    ) -> CallerContext:
        """Discover the caller pane: own env, then an override, then a /proc walk.

        Recovers the launching pane even when the MCP's own environment was
        stripped. Precedence (first source that is inside tmux wins, recorded in
        :attr:`source`):

        1. ``process-env`` -- the server's own ``TMUX``/``TMUX_PANE``.
        2. ``explicit-override`` -- ``LIBTMUX_MCP_CALLER_PANE`` (+ optional
           ``LIBTMUX_MCP_CALLER_TMUX``); the trusted escape hatch.
        3. ``parent-walk`` -- a bounded, same-uid Linux ``/proc`` ancestor climb
           (disabled by ``LIBTMUX_MCP_DISCOVER=0`` or off Linux).

        Never raises: a reader failure, uid mismatch, or missing ``/proc``
        degrades to the next source and ultimately ``source="none"``. The reader
        callables are injectable so the walk is unit-testable without ``/proc``.

        Examples
        --------
        >>> env = {10: {}, 20: {}, 30: {"TMUX_PANE": "%3", "TMUX": "/tmp/s,1,2"}}
        >>> ppid = {10: 20, 20: 30, 30: 1}
        >>> c = CallerContext.discover(
        ...     environ={},
        ...     read_env=env.get,
        ...     read_ppid=ppid.get,
        ...     read_uid=lambda _pid: 1000,
        ...     self_pid=10,
        ...     self_uid=1000,
        ...     is_linux=True,
        ... )
        >>> (c.pane_id, c.socket_path, c.source)
        ('%3', '/tmp/s', 'parent-walk')
        """
        env = os.environ if environ is None else environ
        own = cls.from_env(env)
        if own.in_tmux:
            return own
        override_pane = env.get("LIBTMUX_MCP_CALLER_PANE")
        if override_pane:
            override: dict[str, str] = {"TMUX_PANE": override_pane}
            override_tmux = env.get("LIBTMUX_MCP_CALLER_TMUX")
            if override_tmux:
                override["TMUX"] = override_tmux
            return dataclasses.replace(
                cls.from_env(override),
                source="explicit-override",
            )
        if env.get("LIBTMUX_MCP_DISCOVER") == "0":
            return cls(source="none")
        linux = pathlib.Path("/proc").is_dir() if is_linux is None else is_linux
        if linux:
            walked = cls._parent_walk(
                read_env,
                read_ppid,
                read_uid,
                self_pid,
                self_uid,
                max_depth,
            )
            if walked is not None:
                return walked
        return cls(source="none")

    @classmethod
    def _parent_walk(
        cls,
        read_env: Callable[[int], Mapping[str, str] | None],
        read_ppid: Callable[[int], int | None],
        read_uid: Callable[[int], int | None],
        self_pid: int | None,
        self_uid: int | None,
        max_depth: int,
    ) -> CallerContext | None:
        """Climb the parent chain for the first same-uid ancestor inside tmux."""
        pid = os.getpid() if self_pid is None else self_pid
        uid = os.getuid() if self_uid is None else self_uid
        seen: set[int] = set()
        for _ in range(max_depth):
            ppid = read_ppid(pid)
            if ppid is None or ppid in (0, 1) or ppid in seen:
                return None
            if read_uid(ppid) != uid:
                return None  # never read a foreign or setuid parent's env
            seen.add(ppid)
            env = read_env(ppid)
            if env is None:
                return None
            ctx = cls.from_env(env)
            if ctx.in_tmux:
                return dataclasses.replace(ctx, source="parent-walk")
            pid = ppid
        return None


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


def caller_server_args(caller: CallerContext, *, explicit: bool) -> tuple[str, ...]:
    """Return ``("-S", socket)`` to bind the caller's server, or ``()``.

    Binds only when the caller's socket was discovered and no explicit socket
    override was supplied -- so a stripped-env MCP still drives the user's own
    tmux server instead of spawning a fresh default one.

    Examples
    --------
    >>> caller = CallerContext.from_env({"TMUX_PANE": "%1", "TMUX": "/tmp/s,1,2"})
    >>> caller_server_args(caller, explicit=False)
    ('-S', '/tmp/s')
    >>> caller_server_args(caller, explicit=True)
    ()
    >>> caller_server_args(CallerContext.from_env({}), explicit=False)
    ()
    """
    if explicit or not caller.in_tmux or caller.socket_path is None:
        return ()
    return ("-S", caller.socket_path)


def socket_path_of(socket: str) -> str:
    """Return the filesystem path an engine *socket* selector denotes.

    A ``-S`` selector (anything containing ``/``) already *is* the path. A bare
    ``-L`` name is the per-user socket tmux derives from ``$TMUX_TMPDIR`` (default
    ``/tmp``), so a bare name cannot collide with an unrelated socket's basename.

    Examples
    --------
    >>> socket_path_of("/tmp/explicit")
    '/tmp/explicit'
    >>> socket_path_of("work").endswith("/work")
    True
    """
    if "/" in socket:
        return socket
    tmpdir = os.environ.get("TMUX_TMPDIR") or "/tmp"
    return f"{tmpdir}/tmux-{os.getuid()}/{socket}"


def same_socket_path(left: str, right: str) -> bool:
    """Whether two socket paths point at the same file (realpath-compared).

    Falls back to a literal comparison when the paths cannot be resolved (a
    broken symlink or an unreadable directory must not mask the guard).

    Examples
    --------
    >>> same_socket_path("/tmp/s", "/tmp/s")
    True
    >>> same_socket_path("/tmp/s", "/tmp/other")
    False
    """
    try:
        return os.path.realpath(left) == os.path.realpath(right)
    except OSError:
        return left == right


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
        # An unbound engine talks to the ambient $TMUX server, which is the
        # caller's only when the MCP itself inherited it (process-env). A
        # parent-walked caller's socket is NOT the ambient default.
        return (
            caller.in_tmux
            and caller.socket_path is not None
            and caller.source == "process-env"
        )
    if caller.socket_path is None:
        return False
    return same_socket_path(socket_path_of(socket), caller.socket_path)


def socket_could_match(socket: str | None, caller: CallerContext) -> bool:
    """Conservative socket comparator: True unless the caller is provably elsewhere.

    The fail-safe counterpart to :func:`socket_matches`, for destructive guards:
    it blocks (returns ``True``) whenever it cannot *disprove* that *socket* is
    the caller's server -- an unknown caller socket, an ambient default engine,
    or a last-chance basename match all count, so a self-kill is refused under
    uncertainty (e.g. a ``$TMUX_TMPDIR`` divergence).

    Examples
    --------
    >>> caller = CallerContext.from_env({"TMUX_PANE": "%1", "TMUX": "/tmp/s,1,2"})
    >>> socket_could_match(None, caller)
    True
    >>> socket_could_match("/tmp/s", caller)
    True
    >>> socket_could_match("/tmp/other", caller)
    False
    >>> socket_could_match(None, CallerContext.from_env({}))
    False
    """
    if not caller.in_tmux:
        return False
    if caller.socket_path is None:
        return True
    if socket is None:
        # Ambient default engine: the caller's server only when the MCP inherited
        # $TMUX (process-env), not when its pane was parent-walked or overridden.
        return caller.source == "process-env"
    if same_socket_path(socket_path_of(socket), caller.socket_path):
        return True
    # Last chance for a bare -L name whose reconstructed path did not resolve
    # (e.g. a $TMUX_TMPDIR divergence): a basename match blocks under doubt.
    return "/" not in socket and caller.socket_path.rsplit("/", 1)[-1] == socket


def is_strict_caller(
    pane_id: str | None,
    socket: str | None,
    caller: CallerContext,
) -> bool:
    """Whether *pane_id* on an engine bound to *socket* is the caller's own pane.

    Strict: requires pane-id equality *and* a confirmed socket match, since a
    pane id is unique only within one tmux server. Bare pane-id equality is
    rejected to avoid a cross-server false positive. Used for the ``is_caller``
    annotation and the caller-default origin -- both must demand a positive match.

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
