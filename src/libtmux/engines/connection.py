"""The connection an engine talks to: which tmux binary, which tmux server.

Every engine needs the same two things before it can dispatch anything: a tmux
*binary* to exec, and the *connection flags* (``-L``/``-S``/``-f``/``-2``/``-8``)
that point at one particular tmux server. :class:`ServerConnection` is that pair
as one frozen value, and it is the only place in libtmux where either is
computed -- :meth:`libtmux.Server.cmd`, :meth:`libtmux.Server.raise_if_dead` and
:func:`libtmux.neo.fetch_objs` all read their flags from here.

:meth:`ServerConnection.resolve_bin` is the single door to a tmux binary path: it
memoizes :func:`shutil.which` and raises
:exc:`~libtmux.exc.TmuxCommandNotFound` when tmux is absent, so no engine ships
an unguarded ``shutil.which("tmux")`` of its own.
"""

from __future__ import annotations

import shutil
import typing as t
from dataclasses import dataclass, field

from libtmux import exc

if t.TYPE_CHECKING:
    import pathlib
    from collections.abc import Sequence


class _BinaryResolver:
    """Memoized tmux-binary resolution and ``tmux -V`` probe.

    Owned by a :class:`ServerConnection`; never constructed by engines. Holding
    the mutable cache here keeps :class:`ServerConnection` a frozen, comparable
    value.
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
        once and the answer is cached. A *failure* is not cached, so a tmux
        installed after the miss is picked up.
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
            # Imported here, not at module scope: libtmux.common's tmux_cmd
            # dispatches through this package, so a module-level import would
            # close an import cycle.
            from libtmux.common import get_version

            try:
                self._version = str(get_version(self.resolve()))
            except exc.LibTmuxException:
                self._version = None
        return self._version


@dataclass(frozen=True)
class ServerConnection:
    """Which tmux binary, and which tmux server, an engine talks to.

    Attributes
    ----------
    tmux_bin : str or None
        An explicit tmux binary. ``None`` means "resolve from ``$PATH``", which
        :meth:`resolve_bin` does once and memoizes.
    args : tuple[str, ...]
        Connection flags placed before the tmux subcommand (e.g. ``("-Lwork",)``).
    _resolver : _BinaryResolver
        Memoized resolver for the binary path and tmux version. Built in
        ``__post_init__``; excluded from equality, hashing and :func:`repr`.

    Examples
    --------
    The default connection targets the ambient tmux server:

    >>> ServerConnection()
    ServerConnection(tmux_bin=None, args=())

    :meth:`from_server` reads the flags off a live :class:`libtmux.Server`:

    >>> conn = ServerConnection.from_server(server)
    >>> conn.args[0].startswith(("-L", "-S"))
    True

    It duck-types, so any object with the same attributes works:

    >>> import types
    >>> ServerConnection.from_server(
    ...     types.SimpleNamespace(socket_name="work", colors=256)
    ... )
    ServerConnection(tmux_bin=None, args=('-2', '-Lwork'))

    :meth:`argv` prepends the binary and the flags to a command:

    >>> ServerConnection.of(tmux_bin="tmux", args=("-Lwork",)).argv(
    ...     "kill-window", "-t", "@1"
    ... )
    ('tmux', '-Lwork', 'kill-window', '-t', '@1')
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
        """Normalize *args* and build the connection's binary resolver.

        Examples
        --------
        >>> ServerConnection(args=["-Lwork"]).args
        ('-Lwork',)
        """
        object.__setattr__(self, "args", tuple(self.args))
        object.__setattr__(self, "_resolver", _BinaryResolver(self.tmux_bin))

    @classmethod
    def of(
        cls,
        tmux_bin: str | pathlib.Path | None = None,
        args: Sequence[str] = (),
    ) -> ServerConnection:
        """Build a connection, stringifying a :class:`pathlib.Path` binary.

        Parameters
        ----------
        tmux_bin : str or pathlib.Path, optional
            Explicit tmux binary.
        args : Sequence[str]
            Connection flags.

        Returns
        -------
        ServerConnection
            The connection.

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

        Flags are emitted in tmux's documented order of significance and in the
        order :meth:`libtmux.Server.cmd` has always emitted them: color depth,
        ``-f`` config file, ``-S`` socket path, ``-L`` socket name.

        Parameters
        ----------
        server : typing.Any
            Any object exposing ``socket_name``, ``socket_path``,
            ``config_file``, ``colors`` and ``tmux_bin``. Missing attributes are
            treated as unset.

        Returns
        -------
        ServerConnection
            The connection.

        Raises
        ------
        :exc:`~libtmux.exc.UnknownColorOption`
            ``colors`` is truthy but is neither ``256`` nor ``88``.

        Examples
        --------
        >>> import types
        >>> ServerConnection.from_server(
        ...     types.SimpleNamespace(socket_path="/tmp/s", config_file="/tmp/c")
        ... )
        ServerConnection(tmux_bin=None, args=('-f/tmp/c', '-S/tmp/s'))

        >>> from libtmux import exc
        >>> try:
        ...     ServerConnection.from_server(types.SimpleNamespace(colors=16))
        ... except exc.UnknownColorOption as e:
        ...     print(e)
        Server.colors must equal 88 or 256
        """
        args: list[str] = []

        colors = getattr(server, "colors", None)
        if colors:
            if colors == 256:
                args.append("-2")
            elif colors == 88:
                args.append("-8")
            else:
                raise exc.UnknownColorOption

        if getattr(server, "config_file", None):
            args.append(f"-f{server.config_file}")
        if getattr(server, "socket_path", None):
            args.append(f"-S{server.socket_path}")
        if getattr(server, "socket_name", None):
            args.append(f"-L{server.socket_name}")

        return cls.of(tmux_bin=getattr(server, "tmux_bin", None), args=args)

    @property
    def is_unconfigured(self) -> bool:
        """Whether this connection names no server and no binary of its own.

        An unconfigured connection targets whichever tmux server ``tmux`` would
        reach with no flags. :attr:`Server.engine <libtmux.Server.engine>` reads
        this to decide whether an injected engine should adopt the server's
        connection: an engine that already names a server is left alone, and one
        that names none is bound, so it cannot silently dispatch to the ambient
        server.

        Returns
        -------
        bool

        Examples
        --------
        >>> ServerConnection().is_unconfigured
        True
        >>> ServerConnection.of(args=("-Lwork",)).is_unconfigured
        False
        >>> ServerConnection.of(tmux_bin="/usr/bin/tmux").is_unconfigured
        False
        """
        return not self.args and self.tmux_bin is None

    def resolve_bin(self) -> str:
        """Return the tmux binary path (memoized).

        Returns
        -------
        str
            Path to tmux.

        Raises
        ------
        :exc:`~libtmux.exc.TmuxCommandNotFound`
            tmux is not on ``$PATH`` and none was declared.

        Examples
        --------
        >>> ServerConnection.of(tmux_bin="/usr/bin/tmux").resolve_bin()
        '/usr/bin/tmux'
        """
        return self._resolver.resolve()

    def tmux_version(self) -> str | None:
        """Return this connection's tmux version (memoized), or ``None``.

        Returns
        -------
        str or None
            Version string, e.g. ``"3.5"``; ``None`` when tmux is missing or
            its version cannot be parsed.

        Examples
        --------
        >>> ServerConnection().tmux_version() is not None
        True
        """
        return self._resolver.version()

    def argv(self, *args: str, tmux_bin: str | None = None) -> tuple[str, ...]:
        """Render a full command line: binary, connection flags, then *args*.

        Parameters
        ----------
        *args : str
            The tmux subcommand and its arguments.
        tmux_bin : str, optional
            Override this connection's binary for one command.

        Returns
        -------
        tuple[str, ...]
            The full argv.

        Examples
        --------
        >>> ServerConnection.of("tmux", ("-Lwork",)).argv("list-sessions")
        ('tmux', '-Lwork', 'list-sessions')
        >>> ServerConnection.of("tmux").argv("list-sessions", tmux_bin="/opt/tmux")
        ('/opt/tmux', 'list-sessions')
        """
        return (tmux_bin or self.resolve_bin(), *self.args, *args)
