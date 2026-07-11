"""The connection an engine talks to: which tmux binary, which tmux server.

Every real engine -- subprocess, asyncio, control mode, async control mode, imsg
-- needs the same two things before it can dispatch anything: a tmux *binary* to
exec, and the *connection flags* (``-L``/``-S``/``-f``/``-2``/``-8``) that point
at one particular tmux server. :class:`ServerConnection` is that pair, as one
frozen value object, and it is the *only* place either is computed.

Engines **hold** a connection (``self._conn``) rather than re-deriving one.
:meth:`ServerConnection.resolve_bin` is the single door to a tmux binary path:
it memoizes :func:`shutil.which` and raises
:exc:`~libtmux.exc.TmuxCommandNotFound` when tmux is absent, so an engine cannot
accidentally ship an unguarded, unmemoized ``shutil.which("tmux")`` of its own.
:meth:`ServerConnection.tmux_version` is the matching memoized ``tmux -V`` probe.
"""

from __future__ import annotations

import shutil
import typing as t
from dataclasses import dataclass, field

from libtmux import exc
from libtmux.common import get_version

if t.TYPE_CHECKING:
    import pathlib
    from collections.abc import Sequence


class _BinaryResolver:
    """Memoized tmux-binary resolution and ``tmux -V`` probe.

    Owned by a :class:`ServerConnection`; never constructed by engines. Holding
    the (mutable) cache here keeps :class:`ServerConnection` itself a frozen,
    comparable value.
    """

    __slots__ = ("_declared", "_resolved", "_version", "_version_probed")

    def __init__(self, tmux_bin: str | None = None) -> None:
        self._declared = tmux_bin
        self._resolved: str | None = None
        self._version: str | None = None
        self._version_probed = False

    def resolve(self) -> str:
        """Return the tmux binary path, memoized for this connection.

        An explicit binary wins. Otherwise :func:`shutil.which` walks ``$PATH``
        once -- it costs ~50µs and sits on the hot path of every command -- and
        the answer is cached. A *failure* is not cached, so a tmux installed
        after the miss is picked up.
        """
        if self._declared is not None:
            return self._declared
        if self._resolved is None:
            resolved = shutil.which("tmux")
            if resolved is None:
                raise exc.TmuxCommandNotFound
            self._resolved = resolved
        return self._resolved

    def version(self) -> str | None:
        """Return the tmux version string, memoized; ``None`` when unknowable.

        ``None`` (missing binary, unparseable output) lets version resolution
        degrade to "assume latest" rather than exploding.
        """
        if not self._version_probed:
            self._version_probed = True
            try:
                self._version = str(get_version(self.resolve()))
            except exc.LibTmuxException:
                self._version = None
        return self._version


@dataclass(frozen=True)
class ServerConnection:
    """Which tmux binary, and which tmux server, an engine talks to.

    Parameters
    ----------
    tmux_bin : str or None
        An explicit tmux binary. ``None`` means "resolve from ``$PATH``", which
        :meth:`resolve_bin` does once and memoizes.
    args : tuple[str, ...]
        Connection flags placed before the tmux subcommand (e.g. ``("-Lwork",)``).

    Examples
    --------
    The default connection targets the ambient tmux server:

    >>> ServerConnection()
    ServerConnection(tmux_bin=None, args=())

    :meth:`from_server` reads the flags off a live :class:`libtmux.Server`,
    which is what every engine's ``for_server`` classmethod is built on:

    >>> conn = ServerConnection.from_server(server)
    >>> conn.args[0].startswith(("-L", "-S"))
    True
    >>> conn.tmux_version() == conn.tmux_version()  # memoized
    True

    It duck-types, so a plain object with the same attributes works too:

    >>> import types
    >>> ServerConnection.from_server(
    ...     types.SimpleNamespace(socket_name="work", colors=256)
    ... )
    ServerConnection(tmux_bin=None, args=('-Lwork', '-2'))

    :meth:`argv` prepends the binary and the flags to a rendered command:

    >>> ServerConnection.of(tmux_bin="tmux", args=("-Lwork",)).argv(
    ...     "kill-window", "-t", "@1"
    ... )
    ['tmux', '-Lwork', 'kill-window', '-t', '@1']
    """

    tmux_bin: str | None = None
    args: tuple[str, ...] = ()
    _resolver: _BinaryResolver = field(
        init=False,
        repr=False,
        compare=False,
        hash=False,
    )

    def __post_init__(self) -> None:
        """Normalize *args* and build the connection's binary resolver."""
        object.__setattr__(self, "args", tuple(self.args))
        object.__setattr__(self, "_resolver", _BinaryResolver(self.tmux_bin))

    @classmethod
    def of(
        cls,
        tmux_bin: str | pathlib.Path | None = None,
        args: Sequence[str] = (),
    ) -> ServerConnection:
        """Build a connection, stringifying a :class:`pathlib.Path` binary.

        Examples
        --------
        >>> import pathlib
        >>> ServerConnection.of(pathlib.Path("/usr/bin/tmux")).tmux_bin
        '/usr/bin/tmux'
        >>> ServerConnection.of(args=["-L", "test"]).args
        ('-L', 'test')
        """
        return cls(
            tmux_bin=str(tmux_bin) if tmux_bin is not None else None,
            args=tuple(args),
        )

    @classmethod
    def from_server(cls, server: t.Any) -> ServerConnection:
        """Build the connection a live :class:`libtmux.Server` talks over.

        Mirrors :meth:`libtmux.Server.cmd`'s connection-flag construction, so an
        engine built from it reaches the same tmux server as the object API.

        Examples
        --------
        >>> import types
        >>> ServerConnection.from_server(
        ...     types.SimpleNamespace(socket_path="/tmp/s", config_file="/tmp/c")
        ... )
        ServerConnection(tmux_bin=None, args=('-S/tmp/s', '-f/tmp/c'))
        """
        args: list[str] = []
        if getattr(server, "socket_name", None):
            args.append(f"-L{server.socket_name}")
        if getattr(server, "socket_path", None):
            args.append(f"-S{server.socket_path}")
        if getattr(server, "config_file", None):
            args.append(f"-f{server.config_file}")
        colors = getattr(server, "colors", None)
        if colors == 256:
            args.append("-2")
        elif colors == 88:
            args.append("-8")
        return cls.of(tmux_bin=getattr(server, "tmux_bin", None), args=args)

    def resolve_bin(self) -> str:
        """Return the tmux binary path (memoized).

        Raises :exc:`~libtmux.exc.TmuxCommandNotFound` when tmux is not on
        ``$PATH`` and none was declared -- the guard every engine gets for free.

        Examples
        --------
        >>> ServerConnection.of(tmux_bin="/usr/bin/tmux").resolve_bin()
        '/usr/bin/tmux'
        """
        return self._resolver.resolve()

    def tmux_version(self) -> str | None:
        """Return this connection's tmux version (memoized), or ``None``.

        Examples
        --------
        >>> ServerConnection().tmux_version() is not None
        True
        """
        return self._resolver.version()

    def argv(self, *args: str, tmux_bin: str | None = None) -> list[str]:
        """Render a full command line: binary, connection flags, then *args*.

        *tmux_bin* overrides this connection's binary for one command (a
        :class:`~libtmux.experimental.engines.base.CommandRequest` may carry one).
        """
        return [tmux_bin or self.resolve_bin(), *self.args, *args]
