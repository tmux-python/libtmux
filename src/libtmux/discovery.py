"""Bounded, non-starting probes of caller-selected tmux socket directories."""

from __future__ import annotations

import copy
import dataclasses
import itertools
import math
import os
import pathlib
import stat
import time
import typing as t

from libtmux import exc

if t.TYPE_CHECKING:
    from libtmux.server import Server


@dataclasses.dataclass(frozen=True)
class DiscoveredServer:
    """A borrowed server and the numeric identity returned by its probe.

    A later client may replace this daemon. Discovery does not accept ownership
    or write the reserved ownership token. Use ``server.own()`` to accept the
    daemon that answers at adoption time.
    """

    server: Server
    server_pid: int
    start_time: int


@dataclasses.dataclass(frozen=True)
class DiscoveryDiagnostic:
    """Explain a skipped path, failed probe or exhausted discovery budget."""

    path: str
    reason: str
    error: Exception | None = None


@dataclasses.dataclass(frozen=True)
class DiscoveryResult:
    """Return discovered servers, diagnostics and the work performed.

    ``truncated`` means a budget stopped the scan before it could finish.
    ``entries`` counts roots and directory entries; ``probes`` counts tmux
    clients. Results describe these directories during this call, rather than
    a complete inventory of the machine.
    """

    servers: tuple[DiscoveredServer, ...]
    diagnostics: tuple[DiscoveryDiagnostic, ...]
    truncated: bool
    entries: int
    probes: int


def _probe_server(client: Server, timeout: float) -> DiscoveredServer:
    """Read a daemon identity without creating a directory or starting tmux."""
    probe = copy.copy(client)
    probe._socket_name = None
    # A C-locale tmux client replaces control-character delimiters with '_'.
    result = probe.cmd("display-message", "-p", "#{pid}|#{start_time}", timeout=timeout)
    if result.returncode or result.stderr:
        raise exc.LibTmuxException(
            "\n".join(result.stderr) or f"exit status {result.returncode}",
            subcommand="discover-server",
        )
    fields = result.stdout[0].split("|") if len(result.stdout) == 1 else []
    if (
        len(fields) != 2
        or any(not part.isascii() or not part.isdecimal() for part in fields)
        or int(fields[0]) <= 0
    ):
        message = "tmux returned an invalid discovery identity"
        raise exc.LibTmuxException(message)
    return DiscoveredServer(probe, int(fields[0]), int(fields[1]))


def _discover(
    client: Server,
    roots: t.Iterable[str | pathlib.Path],
    *,
    include_configured: bool,
    max_entries: int,
    max_probes: int,
    timeout: float,
    probe_timeout: float,
) -> DiscoveryResult:
    """Scan direct socket children while accounting for filesystem and probe work."""
    for name, value in (("max_entries", max_entries), ("max_probes", max_probes)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            message = f"{name} must be a positive integer"
            raise ValueError(message)
    for name, duration in (("timeout", timeout), ("probe_timeout", probe_timeout)):
        if not math.isfinite(duration) or duration <= 0:
            message = f"{name} must be positive and finite"
            raise ValueError(message)
    deadline = time.monotonic() + timeout
    found: list[DiscoveredServer] = []
    diagnostics: list[DiscoveryDiagnostic] = []
    entries = probes = 0
    truncated = False
    visited_roots: set[tuple[int, int]] = set()
    visited_sockets: set[tuple[int, int]] = set()

    def limited(path: str) -> bool:
        nonlocal truncated
        if time.monotonic() >= deadline:
            reason = "deadline"
        elif entries >= max_entries:
            reason = "entry-limit"
        elif probes >= max_probes:
            reason = "probe-limit"
        else:
            return False
        diagnostics.append(DiscoveryDiagnostic(path, reason))
        truncated = True
        return True

    def candidate(path: str) -> None:
        nonlocal probes
        try:
            metadata = os.stat(path)  # noqa: PTH116 - retain filesystem components
        except OSError as failure:
            diagnostics.append(DiscoveryDiagnostic(path, "entry-error", failure))
            return
        if not stat.S_ISSOCK(metadata.st_mode):
            diagnostics.append(DiscoveryDiagnostic(path, "not-socket"))
            return
        if metadata.st_uid != os.getuid():
            diagnostics.append(DiscoveryDiagnostic(path, "other-owner"))
            return
        identity = metadata.st_dev, metadata.st_ino
        if identity in visited_sockets:
            return
        visited_sockets.add(identity)
        probe = copy.copy(client)
        probe._socket_path = path
        probe._socket_name = None
        probes += 1
        try:
            found.append(
                _probe_server(
                    probe, min(probe_timeout, max(0.001, deadline - time.monotonic()))
                )
            )
        except Exception as failure:  # noqa: BLE001 - diagnostic retains the failure
            diagnostics.append(DiscoveryDiagnostic(path, "probe-error", failure))

    configured: tuple[str, ...] = ()
    if include_configured:
        entries += 1
        candidate(client.socket_path)
        root = client.child_environment.get("TMUX_TMPDIR") or "/tmp"
        configured = (
            os.path.dirname(client.socket_path),  # noqa: PTH120 - retain spelling
            f"{root}/tmux-{os.getuid()}",
            f"/tmp/tmux-{os.getuid()}",
        )
    directories = iter(itertools.chain(roots, configured))
    while not limited(""):
        try:
            path = str(next(directories))
        except StopIteration:
            break
        entries += 1
        if not pathlib.Path(path).is_absolute() or "\0" in path:
            diagnostics.append(DiscoveryDiagnostic(path, "invalid-root"))
            continue
        try:
            metadata = os.stat(path)  # noqa: PTH116 - retain filesystem components
            identity = metadata.st_dev, metadata.st_ino
            if identity in visited_roots:
                continue
            visited_roots.add(identity)
            with os.scandir(path) as children:
                while not limited(path):
                    try:
                        child = next(children)
                    except StopIteration:
                        break
                    entries += 1
                    candidate(child.path)
        except OSError as failure:
            diagnostics.append(DiscoveryDiagnostic(path, "root-error", failure))
        if truncated:
            break
    return DiscoveryResult(tuple(found), tuple(diagnostics), truncated, entries, probes)
