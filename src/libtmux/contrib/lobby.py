"""Discover local tmux servers through their Unix sockets."""

from __future__ import annotations

import collections.abc
import contextlib
import math
import os
import pathlib
import stat
import subprocess
import typing as t
from dataclasses import dataclass

from libtmux import exc
from libtmux._internal.env import socket_path_from_env
from libtmux._internal.query_list import QueryList
from libtmux.server import Server

if t.TYPE_CHECKING:
    from libtmux._internal.types import StrPath
    from libtmux.pane import Pane
    from libtmux.session import Session
    from libtmux.window import Window


@dataclass
class TmuxLobbyServer:
    """Describe a socket and the tmux probe made during a scan.

    Failed probes remain in the results. An unresponsive socket may belong
    to a stopped tmux server, another program, or an inaccessible server;
    ``alive=False`` does not distinguish those cases. Read ``error`` for the
    probe's diagnostic. Access the lobby's ``servers`` again to rescan.

    Attributes
    ----------
    alive : bool
        Whether the probe received tmux's server metadata.
    server : libtmux.server.Server
        Server bound to the discovered path. Commands use this exact socket.
    socket_name : str
        Basename of the resolved path; not necessarily a tmux ``-L`` name.
    socket_path : str
        Absolute, resolved socket path; the result's identity.
    uid : int
        Socket owner's user ID at discovery.
    pid : int, optional
        Server process ID reported by tmux, absent on a failed probe.
    version : str, optional
        Server version reported by tmux, absent on a failed probe.
    error : str, optional
        Probe failure text, or ``None`` after a successful probe.
    """

    alive: bool
    server: Server
    socket_name: str
    socket_path: str
    uid: int
    pid: int | None = None
    version: str | None = None
    error: str | None = None

    @property
    def sessions(self) -> QueryList[Session]:
        """Query current sessions; return empty after a failed probe or query."""
        if not self.alive:
            return QueryList()
        try:
            return self.server.sessions
        except (exc.LibTmuxException, OSError, subprocess.SubprocessError):
            return QueryList()

    @property
    def windows(self) -> QueryList[Window]:
        """Query current windows; return empty after a failed probe or query."""
        if not self.alive:
            return QueryList()
        try:
            return self.server.windows
        except (exc.LibTmuxException, OSError, subprocess.SubprocessError):
            return QueryList()

    @property
    def panes(self) -> QueryList[Pane]:
        """Query current panes; return empty after a failed probe or query."""
        if not self.alive:
            return QueryList()
        try:
            return self.server.panes
        except (exc.LibTmuxException, OSError, subprocess.SubprocessError):
            return QueryList()


class _Servers:
    """Scan defaults on class access, or the instance's configured paths."""

    def __get__(
        self,
        instance: TmuxLobby | None,
        owner: type[TmuxLobby],
    ) -> QueryList[TmuxLobbyServer]:
        return (instance if instance is not None else owner())._scan()


class TmuxLobby:
    """Find sockets and probe them for tmux servers without starting a server.

    ``TmuxLobby.servers`` scans the current user's tmux directories under
    ``/tmp`` and ``$TMUX_TMPDIR``, plus the socket in ``$TMUX``. Construct a
    lobby to add search locations or replace the defaults. Environment
    variables are read on each scan.

    Parameters
    ----------
    paths : str, os.PathLike, or iterable of paths, optional
        Socket files or directories whose immediate children are searched.
        ``~`` is expanded. Relative paths use the working directory at scan
        time. Missing and unreadable locations are skipped.
    patterns : str or iterable of str, optional
        Glob patterns for socket files or directories. ``**`` searches
        recursively. Patterns are expanded separately from literal paths.
    include_defaults : bool
        Include the default locations alongside ``paths`` and ``patterns``.
        Set to ``False`` to search only the locations supplied.
    timeout : float
        Positive, finite seconds per probe; defaults to one second. Probes
        run sequentially. This limit does not apply to subsequent commands
        through a result's ``server`` or child accessors.
    tmux_bin : str or os.PathLike, optional
        tmux client binary used for probes and returned servers.

    Attributes
    ----------
    servers : QueryList[TmuxLobbyServer]
        A fresh scan on each access, sorted by resolved socket path and
        deduplicated by that path. Regular files are excluded. Results use
        the existing ``filter`` and ``get`` lookups, including ``alive``
        and ``socket_name__startswith``. Filtering does not rescan.

    Raises
    ------
    ValueError
        When ``timeout`` is not positive and finite.
    """

    servers = _Servers()
    """Scan for sockets and return their probe results.

    :meta hide-value:
    """

    def __init__(
        self,
        paths: StrPath | collections.abc.Iterable[StrPath] = (),
        *,
        patterns: str | collections.abc.Iterable[str] = (),
        include_defaults: bool = True,
        timeout: float = 1.0,
        tmux_bin: StrPath | None = None,
    ) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            msg = "timeout must be positive and finite"
            raise ValueError(msg)
        if isinstance(paths, (str, os.PathLike)):
            paths = (paths,)
        if isinstance(patterns, str):
            patterns = (patterns,)
        self._paths = tuple(pathlib.Path(path) for path in paths)
        self._patterns = tuple(patterns)
        self._include_defaults = include_defaults
        self._timeout = timeout
        self._tmux_bin = str(tmux_bin) if tmux_bin is not None else None

    @staticmethod
    def _default_paths() -> list[pathlib.Path]:
        directory = f"tmux-{os.getuid()}"
        paths = [pathlib.Path("/tmp") / directory]
        if tmpdir := os.environ.get("TMUX_TMPDIR"):
            paths.append(pathlib.Path(tmpdir) / directory)
        with contextlib.suppress(exc.NotInsideTmux):
            paths.append(pathlib.Path(socket_path_from_env()))
        return paths

    def _candidates(self) -> collections.abc.Iterator[pathlib.Path]:
        paths = list(self._paths)
        if self._include_defaults:
            paths.extend(self._default_paths())
        for pattern in self._patterns:
            pattern_path = pathlib.Path(pattern).expanduser()
            root = pathlib.Path(pattern_path.anchor)
            with contextlib.suppress(OSError):
                paths.extend(root.glob(str(pattern_path.relative_to(root))))
        for path in paths:
            with contextlib.suppress(OSError):
                path = path.expanduser()
                if path.is_dir():
                    yield from path.iterdir()
                else:
                    yield path

    def _scan(self) -> QueryList[TmuxLobbyServer]:
        sockets: dict[pathlib.Path, os.stat_result] = {}
        for path in self._candidates():
            try:
                path = path.resolve()
                info = path.stat()
            except (OSError, RuntimeError):
                continue
            if stat.S_ISSOCK(info.st_mode):
                sockets[path] = info
        return QueryList(self._probe(path, sockets[path]) for path in sorted(sockets))

    def _probe(self, path: pathlib.Path, info: os.stat_result) -> TmuxLobbyServer:
        server = Server(socket_path=str(path), tmux_bin=self._tmux_bin)
        result = TmuxLobbyServer(
            alive=False,
            server=server,
            socket_name=path.name,
            socket_path=str(path),
            uid=info.st_uid,
        )
        try:
            proc = server.cmd(
                "-N",
                "display-message",
                "-p",
                "#{pid}\t#{version}",
                timeout=self._timeout,
            )
        except (exc.LibTmuxException, OSError, subprocess.SubprocessError) as error:
            result.error = str(error) or type(error).__name__
            return result
        if proc.returncode:
            result.error = (
                "\n".join(proc.stderr) or f"tmux exited with status {proc.returncode}"
            )
            return result
        if len(proc.stdout) == 1:
            pid, separator, version = proc.stdout[0].partition("\t")
            if separator and pid.isdecimal() and int(pid) > 0 and version:
                result.alive = True
                result.pid = int(pid)
                result.version = version
                return result
        result.error = "tmux returned no server metadata"
        return result
