"""Isolation, shapes, and statistics shared by libtmux's benchmarks.

Everything here works against what libtmux ships today -- the classic
:class:`~libtmux.Server` object hierarchy -- so a benchmark of any later
transport can reuse it without dragging that transport's imports along.

The hermetic-isolation half is the part worth sharing rather than copying: it
encodes two tmux behaviours that cost real debugging time, and a second copy
would be free to forget either of them. See :func:`new_server` for the
``exit-empty`` race and :func:`reap_stale_scratch` for why a scratch directory
with a live server is left alone.
"""

from __future__ import annotations

import atexit
import contextlib
import itertools
import math
import os
import pathlib
import shutil
import statistics
import subprocess
import tempfile
import uuid

from libtmux.server import Server

__all__ = [
    "KEEPALIVE",
    "SERVERS",
    "SOCK_DIR",
    "STAT_LABELS",
    "build_classic",
    "cleanup",
    "new_server",
    "parse_shape",
    "percentile",
    "reap_stale_scratch",
    "summarize",
    "uniq",
]

STAT_LABELS = ("n", "min", "avg", "median", "p90", "p95", "p99", "max")

_ctr = itertools.count()

#: Short scratch root: an AF_UNIX path is capped at 107 bytes, and a socket
#: under a deep temporary directory is how that limit gets hit.
SOCK_DIR = pathlib.Path(tempfile.mkdtemp(prefix="ltbench-"))
SERVERS: list[Server] = []
#: A session every bench server keeps for its whole life, so killing a cell's
#: session never drops the server to zero and trips tmux's exit-empty teardown.
KEEPALIVE = "keepalive"


def new_server() -> Server:
    """Return a fresh isolated server on a unique socket under the scratch dir.

    The server is pinned alive by a keepalive session. Every cell kills its
    session between builds, which would otherwise drop the server to zero
    sessions; under tmux's ``exit-empty`` default the server then starts
    exiting, and the next build's ``new-session`` can reach the still-bound
    socket mid-shutdown and fail with "server exited unexpectedly". The race is
    load-dependent, so it surfaced as an intermittent create failure rather than
    an obvious teardown bug. Control mode never hit it -- its ``tmux -C``
    phantom session already pinned the server -- which is exactly why only the
    subprocess cells were affected.

    The configuration is excluded too. A unique socket isolates this server
    from other servers; it says nothing about ``~/.tmux.conf``, which tmux
    reads at server start and which would otherwise fold the machine's
    history limits, hooks, and shell choice into every measurement.
    """
    srv = Server(
        socket_path=str(SOCK_DIR / f"{uuid.uuid4().hex[:8]}.sock"),
        config_file=os.devnull,
    )
    SERVERS.append(srv)
    # The keepalive has to come first: `start-server` alone leaves a server with
    # zero sessions, which exits immediately under the default, so there is no
    # server left to set the option on. Creating a session that is never killed
    # is what actually holds the floor above zero.
    srv.cmd("new-session", "-d", "-s", KEEPALIVE)
    srv.cmd("set-option", "-s", "exit-empty", "off")
    return srv


def cleanup() -> None:
    """Kill every server this process started and remove its scratch dir."""
    for srv in SERVERS:
        with contextlib.suppress(Exception):
            srv.kill()
    # Backstop: SIGKILL any tmux server still bound to a socket in our dir.
    with contextlib.suppress(Exception):
        out = subprocess.run(
            ["pgrep", "-f", f"tmux .*-S{SOCK_DIR}/"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.split()
        for pid in out:
            with contextlib.suppress(Exception):
                os.kill(int(pid), 9)
    with contextlib.suppress(Exception):
        shutil.rmtree(SOCK_DIR, ignore_errors=True)


def reap_stale_scratch() -> int:
    """Remove scratch dirs left by runs that died before their cleanup.

    :func:`cleanup` only knows *this* process's socket dir, so a run killed
    before its ``atexit`` hook leaves its dir -- and any tmux still bound to
    it -- behind for good. Those survivors keep consuming CPU and file
    descriptors, and machine load is precisely what makes the server-teardown
    race fire, so an unreaped leak feeds the very failure it came from.

    A dir with a live tmux is left alone: it may belong to a concurrent run, and
    stealing another run's servers would be worse than leaking. That means hung
    clients are only reclaimed once their server is gone, which is the
    conservative trade.

    Returns
    -------
    int
        How many stale directories were removed. Reporting is the caller's
        job, so this module needs no console of its own.
    """
    reaped = 0
    for path in pathlib.Path(tempfile.gettempdir()).glob("ltbench-*"):
        if path == SOCK_DIR or not path.is_dir():
            continue
        with contextlib.suppress(Exception):
            alive = subprocess.run(
                ["pgrep", "-f", f"tmux .*-S{path}/"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.split()
            if alive:
                continue
            shutil.rmtree(path, ignore_errors=True)
            reaped += 1
    return reaped


atexit.register(cleanup)


def uniq() -> str:
    """Return a process-unique session name (never collides across builds)."""
    return f"b{next(_ctr)}"


def parse_shape(s: str) -> tuple[int, int]:
    """'8x4' -> (8 windows, 4 panes-per-window)."""
    w, _, p = s.lower().partition("x")
    return int(w), int(p)


def build_classic(server: Server, name: str, wins: int, panes: int) -> None:
    """Build the structure with the classic Server/Session/Window/Pane API."""
    session = server.new_session(session_name=name, window_name="w0")
    for _ in range(panes - 1):
        session.active_window.split()
    for wi in range(1, wins):
        window = session.new_window(window_name=f"w{wi}")
        for _ in range(panes - 1):
            window.split()


def percentile(sorted_vals: list[float], pct: float) -> float:
    """Nearest-rank percentile of a pre-sorted sequence."""
    if not sorted_vals:
        return float("nan")
    rank = max(1, math.ceil(pct / 100.0 * len(sorted_vals)))
    return sorted_vals[min(rank, len(sorted_vals)) - 1]


def summarize(samples: list[float]) -> dict[str, float]:
    """Return min/avg/median/p90/p95/p99/max (and n) for *samples*."""
    s = sorted(samples)
    return {
        "n": float(len(s)),
        "min": s[0],
        "avg": statistics.fmean(s),
        "median": statistics.median(s),
        "p90": percentile(s, 90),
        "p95": percentile(s, 95),
        "p99": percentile(s, 99),
        "max": s[-1],
    }
