"""Server connection representation and constraint merging."""

from __future__ import annotations

import shutil
import typing as t
from dataclasses import dataclass, field

from libtmux import exc
from libtmux._internal.invocation import parse_client_options

if t.TYPE_CHECKING:
    import pathlib


@dataclass(frozen=True, slots=True)
class _ConnectionSettings:
    """Normalized tmux client-level connection settings.

    Attributes
    ----------
    socket_name : str or None
        Effective ``-L`` socket name when specified.
    socket_path : str or None
        Effective ``-S`` socket path when specified.
    config_files : tuple[str, ...]
        Ordered ``-f`` configuration file paths.
    colors : int or None
        Terminal color depth (``256`` for ``-2``, ``88`` for ``-8``).
    """

    socket_name: str | None = None
    socket_path: str | None = None
    config_files: tuple[str, ...] = ()
    colors: int | None = None

    @property
    def socket(self) -> tuple[str, str] | None:
        if self.socket_path is not None:
            return ("path", self.socket_path)
        if self.socket_name is not None:
            return ("name", self.socket_name)
        return None


@dataclass(frozen=True, slots=True)
class ConnectionResolution:
    """Outcome of overlaying :class:`~libtmux.Server` constraints onto an engine.

    Attributes
    ----------
    connection : ServerConnection
        Merged target connection.
    conflicts : tuple[str, ...]
        Explicit settings where the server and engine disagree.
    missing : tuple[str, ...]
        Server settings that require rebinding the engine.
    """

    connection: ServerConnection
    conflicts: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()


def _connection_settings(args: t.Sequence[str]) -> _ConnectionSettings:
    socket_name: str | None = None
    socket_path: str | None = None
    config_files: list[str] = []
    colors: int | None = None

    for opt in parse_client_options(args):
        if opt.name == "2":
            colors = 256
        elif opt.name == "8":
            colors = 88
        elif opt.name == "f" and opt.value is not None:
            config_files.append(opt.value)
        elif opt.name == "L" and opt.value is not None:
            socket_name = opt.value
        elif opt.name == "S" and opt.value is not None:
            socket_path = opt.value

    return _ConnectionSettings(
        socket_name=socket_name,
        socket_path=socket_path,
        config_files=tuple(config_files),
        colors=colors,
    )


def merge_connection_constraints(
    connection: ServerConnection,
    constraints: ServerConnection,
) -> ConnectionResolution:
    """Overlay explicit :class:`~libtmux.Server` constraints onto *connection*.

    Non-conflicting missing settings are appended in canonical order; explicit
    contradictions are recorded in ``conflicts`` so :attr:`Server.engine` can
    raise :exc:`~libtmux.exc.EngineConfigurationMismatch`.

    Examples
    --------
    >>> from libtmux._internal.connection import (
    ...     ServerConnection,
    ...     merge_connection_constraints,
    ... )
    >>> merge_connection_constraints(
    ...     ServerConnection.of(args=("-Lone",)),
    ...     ServerConnection.of(args=("-Ltwo",)),
    ... ).conflicts
    ('socket',)
    >>> merge_connection_constraints(
    ...     ServerConnection.of(tmux_bin="/opt/tmux"),
    ...     ServerConnection.of(args=("-Lwork",)),
    ... ).connection
    ServerConnection(tmux_bin='/opt/tmux', args=('-Lwork',))
    """
    current = _connection_settings(connection.args)
    required = _connection_settings(constraints.args)
    conflicts: list[str] = []
    missing: list[str] = []
    additions: list[str] = []

    tmux_bin = connection.tmux_bin
    if constraints.tmux_bin is not None:
        if tmux_bin is None:
            tmux_bin = constraints.tmux_bin
            missing.append("binary")
        elif tmux_bin != constraints.tmux_bin:
            conflicts.append("binary")

    if required.colors is not None:
        if current.colors is None:
            additions.append("-2" if required.colors == 256 else "-8")
            missing.append("color")
        elif current.colors != required.colors:
            conflicts.append("color")

    if required.config_files:
        if not current.config_files:
            additions.extend(f"-f{path}" for path in required.config_files)
            missing.append("config")
        elif current.config_files != required.config_files:
            conflicts.append("config")

    if required.socket is not None:
        if current.socket is None:
            kind, value = required.socket
            additions.append(f"-{'L' if kind == 'name' else 'S'}{value}")
            missing.append("socket")
        elif current.socket != required.socket:
            conflicts.append("socket")

    return ConnectionResolution(
        connection=ServerConnection.of(
            tmux_bin=tmux_bin,
            args=(*connection.args, *additions),
        ),
        conflicts=tuple(conflicts),
        missing=tuple(missing),
    )


class _BinaryResolver:
    """Memoized tmux binary path and version probe."""

    __slots__ = ("_declared", "_resolved", "_version", "_version_probed")

    def __init__(self, tmux_bin: str | None = None) -> None:
        self._declared = tmux_bin
        self._resolved: str | None = None
        self._version: str | None = None
        self._version_probed = False

    def resolve(self) -> str:
        if self._declared is not None:
            return self._declared
        if self._resolved is None:
            resolved = shutil.which("tmux")
            if resolved is None:
                raise exc.TmuxCommandNotFound
            self._resolved = resolved
        return self._resolved

    def version(self) -> str | None:
        if not self._version_probed:
            self._version_probed = True
            from libtmux.common import get_version_str

            try:
                self._version = get_version_str(self.resolve())
            except exc.LibTmuxException:
                self._version = None
        return self._version


@dataclass(frozen=True)
class ServerConnection:
    """Tmux executable and client connection flags targeting one server.

    Attributes
    ----------
    tmux_bin : str or None
        Explicit tmux executable path, or ``None`` to resolve ``tmux`` on ``$PATH``.
    args : tuple[str, ...]
        Client flags placed before the tmux subcommand (for example ``("-Lwork",)``).
    _resolver : _BinaryResolver
        Memoized resolver for the binary path and tmux version. Built in
        ``__post_init__``; excluded from equality, hashing, and :func:`repr`.

    Examples
    --------
    >>> from libtmux._internal.connection import ServerConnection
    >>> ServerConnection.of("tmux", ("-Lwork",)).argv("list-sessions")
    ('tmux', '-Lwork', 'list-sessions')
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
        object.__setattr__(self, "args", tuple(self.args))
        object.__setattr__(self, "_resolver", _BinaryResolver(self.tmux_bin))

    @classmethod
    def of(
        cls,
        tmux_bin: str | pathlib.Path | None = None,
        args: t.Sequence[str] = (),
    ) -> ServerConnection:
        """Construct a connection from a binary path and flag sequence."""
        return cls(
            tmux_bin=str(tmux_bin) if tmux_bin is not None else None,
            args=tuple(args),
        )

    @classmethod
    def from_server(cls, server: t.Any) -> ServerConnection:
        """Derive connection flags from a :class:`~libtmux.Server`-like object."""
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
        """Return ``True`` when neither flags nor an explicit binary are set."""
        return not self.args and self.tmux_bin is None

    @property
    def names_server(self) -> bool:
        """Return ``True`` when ``args`` carry an effective ``-L`` or ``-S`` flag."""
        return _connection_settings(self.args).socket is not None

    def resolve_bin(self) -> str:
        """Resolve and memoize the tmux binary path."""
        return self._resolver.resolve()

    def tmux_version(self) -> str | None:
        """Return the memoized raw tmux version string, or ``None``."""
        return self._resolver.version()

    def argv(self, *args: str, tmux_bin: str | None = None) -> tuple[str, ...]:
        """Render full argv with executable, connection flags, and *args*."""
        return (tmux_bin or self.resolve_bin(), *self.args, *args)
