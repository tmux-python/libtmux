#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["rich>=13", "typer>=0.12", "libtmux"]
#
# [tool.uv.sources]
# libtmux = { path = "..", editable = true }
# ///
"""Hermetic libtmux engine build-benchmark grid.

Measures how long the experimental workspace builder (and the classic API, and a
hand-rolled pipelined prototype) take to build tmux session structures, sweeping
scenarios x engines x wait-modes. Reports min/avg/median/max/p90/p95/p99.

Hermetic & sandboxed: every server runs on its OWN socket under a throwaway
mkdtemp dir; ``TMUX`` is unset at import so the ambient session is never touched;
an ``atexit`` hook kills every spawned server (and any orphan on our sockets) and
removes the dir. The default server is never contacted.

Engines (``--engines``):
  classic       classic libtmux Server/Session/Window/Pane API (subprocess)
  subprocess    builder on SubprocessEngine     (one tmux fork per op)
  control_mode  builder on ControlModeEngine    (one persistent ``tmux -C``)
  imsg          builder on ImsgEngine           (AF_UNIX imsg, socket-injected)
  concrete      builder on ConcreteEngine       (offline, in-memory: Python floor)
  pipelined     prototype: batch independent creates via run_batch (control_mode)

Timing (``run`` = in-process build-only, the clean signal; ``--hyperfine`` also
runs whole-process wall time via hyperfine over the ``cell`` subcommand).

Run:  uv run bench_engines.py run
      uv run bench_engines.py run --engines control_mode,pipelined --wait
      uv run bench_engines.py profile --engine control_mode --shape 8x4
      uv run bench_engines.py cell control_mode 8x4     # one build (for hyperfine)
"""

from __future__ import annotations

import atexit
import contextlib
import cProfile
import dataclasses
import io
import itertools
import json
import math
import os
import pathlib
import pstats
import shutil
import statistics
import subprocess
import tempfile
import time
import typing as t
import uuid

# Never inherit the ambient tmux session -- do this BEFORE importing libtmux.
os.environ.pop("TMUX", None)
os.environ.pop("TMUX_PANE", None)

import rich.console
import rich.table
import typer

from libtmux.experimental.engines import (
    ConcreteEngine,
    ControlModeEngine,
    ImsgEngine,
    SubprocessEngine,
)
from libtmux.experimental.engines.base import CommandRequest
from libtmux.experimental.workspace import Pane, Window, Workspace
from libtmux.server import Server

console = rich.console.Console()
R = CommandRequest.from_args
_ctr = itertools.count()
STAT_LABELS = ("n", "min", "avg", "median", "p90", "p95", "p99", "max")

# --------------------------------------------------------------------------- #
# Hermetic isolation                                                          #
# --------------------------------------------------------------------------- #
_SOCK_DIR = pathlib.Path(
    tempfile.mkdtemp(prefix="ltbench-")
)  # short: /tmp/ltbench-XXXX
_SERVERS: list[Server] = []


def new_server() -> Server:
    """Return a fresh isolated server on a unique socket under the scratch dir."""
    srv = Server(socket_path=str(_SOCK_DIR / f"{uuid.uuid4().hex[:8]}.sock"))
    _SERVERS.append(srv)
    return srv


def _cleanup() -> None:
    for srv in _SERVERS:
        with contextlib.suppress(Exception):
            srv.kill()
    # Backstop: SIGKILL any tmux server still bound to a socket in our dir.
    with contextlib.suppress(Exception):
        out = subprocess.run(
            ["pgrep", "-f", f"tmux .*-S{_SOCK_DIR}/"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.split()
        for pid in out:
            with contextlib.suppress(Exception):
                os.kill(int(pid), 9)
    with contextlib.suppress(Exception):
        shutil.rmtree(_SOCK_DIR, ignore_errors=True)


atexit.register(_cleanup)


def uniq() -> str:
    """Return a process-unique session name (never collides across builds)."""
    return f"b{next(_ctr)}"


# --------------------------------------------------------------------------- #
# Scenario spec + build implementations                                       #
# --------------------------------------------------------------------------- #
def parse_shape(s: str) -> tuple[int, int]:
    """'8x4' -> (8 windows, 4 panes-per-window)."""
    w, _, p = s.lower().partition("x")
    return int(w), int(p)


def spec(name: str, wins: int, panes: int) -> Workspace:
    """Build the declarative Workspace IR for *wins* windows x *panes* panes."""
    return Workspace(
        name=name,
        on_exists="replace",
        windows=[
            Window(name=f"w{w}", panes=[Pane() for _ in range(panes)])
            for w in range(wins)
        ],
    )


def build_classic(server: Server, name: str, wins: int, panes: int) -> None:
    """Build the structure with the classic Server/Session/Window/Pane API."""
    session = server.new_session(session_name=name, window_name="w0")
    for _ in range(panes - 1):
        session.active_window.split()
    for wi in range(1, wins):
        window = session.new_window(window_name=f"w{wi}")
        for _ in range(panes - 1):
            window.split()


def build_pipelined(engine: t.Any, name: str, wins: int, panes: int) -> None:
    """Prototype: batch INDEPENDENT creates into few run_batch round-trips.

    new-session (1) + all new-windows in one run_batch (1) + all splits in one
    run_batch (1) = 3 round-trips for any shape, vs ~1-per-op for the builder.
    The control-mode run_batch pipelines (write all, read all reply blocks).
    """
    engine.run(R("new-session", "-d", "-s", name, "-n", "w0"))
    if wins > 1:
        engine.run_batch(
            [R("new-window", "-t", name, "-n", f"w{i}") for i in range(1, wins)]
        )
    splits = [
        R("split-window", "-t", f"{name}:w{i}")
        for i in range(wins)
        for _ in range(panes - 1)
    ]
    if splits:
        engine.run_batch(splits)


class ImsgForServer:
    """Bind ImsgEngine to a specific server by injecting ``-S<socket>`` per call.

    ImsgEngine has no ``for_server`` -- it parses ``-L``/``-S`` from the command
    args -- so this wrapper prepends the isolated socket flag to every request.
    """

    def __init__(self, server: Server) -> None:
        self._e = ImsgEngine()
        self._flag = (
            f"-S{server.socket_path}"
            if server.socket_path
            else f"-L{server.socket_name}"
        )

    def run(self, req: CommandRequest) -> t.Any:
        """Run one request with the socket flag injected."""
        return self._e.run(R(self._flag, *req.args))

    def run_batch(self, reqs: t.Sequence[CommandRequest]) -> t.Any:
        """Run a batch of requests, each with the socket flag injected."""
        return self._e.run_batch([R(self._flag, *r.args) for r in reqs])

    def tmux_version(self) -> t.Any:
        """Report the underlying imsg engine's tmux version."""
        return self._e.tmux_version()


@dataclasses.dataclass(frozen=True)
class Impl:
    """One benchmarked implementation: how to make its engine and build."""

    name: str
    kind: str  # classic | builder | pipelined | offline
    make_engine: t.Callable[[Server | None], t.Any] | None = None
    needs_preboot: bool = False
    preflight: bool = True


IMPLS: dict[str, Impl] = {
    "classic": Impl("classic", "classic"),
    "subprocess": Impl(
        "subprocess", "builder", lambda s: SubprocessEngine.for_server(s)
    ),
    "control_mode": Impl(
        "control_mode", "builder", lambda s: ControlModeEngine.for_server(s)
    ),
    "imsg": Impl("imsg", "builder", lambda s: ImsgForServer(s), needs_preboot=True),
    "concrete": Impl(
        "concrete", "offline", lambda s: ConcreteEngine(), preflight=False
    ),
    "pipelined": Impl(
        "pipelined", "pipelined", lambda s: ControlModeEngine.for_server(s)
    ),
}


def do_build(
    impl: Impl, server: Server | None, engine: t.Any, name: str, w: int, p: int
) -> None:
    """Dispatch one build of *w* x *p* to the right implementation path."""
    if impl.kind == "classic":
        build_classic(server, name, w, p)  # type: ignore[arg-type]
    elif impl.kind == "pipelined":
        build_pipelined(engine, name, w, p)
    else:  # builder / offline
        spec(name, w, p).build(engine, preflight=impl.preflight)


def wait_ready(
    server: Server, name: str, timeout: float = 2.0, interval: float = 0.015
) -> None:
    """Poll each pane until its shell has drawn something (a prompt) or timeout.

    Models the classic ``_wait_for_pane_ready`` cost -- the shell-readiness wait
    that inflates 'realistic' build times. Engine-agnostic (reads via subprocess).
    """
    ids = [
        x
        for x in server.cmd("list-panes", "-s", "-t", name, "-F", "#{pane_id}").stdout
        if x
    ]
    pending = set(ids)
    deadline = time.monotonic() + timeout
    while pending and time.monotonic() < deadline:
        for pid in list(pending):
            cap = server.cmd("capture-pane", "-p", "-t", pid).stdout
            if any(line.strip() for line in cap):
                pending.discard(pid)
        if pending:
            time.sleep(interval)


def run_cell(
    impl: Impl, wins: int, panes: int, wait: bool, runs: int, warmup: int
) -> list[float]:
    """Return per-build wall times (ms), in-process, with session cleanup."""
    if impl.kind == "offline":
        engine = impl.make_engine(None)  # type: ignore[misc]
        for _ in range(warmup):
            spec(uniq(), wins, panes).build(engine, preflight=False)
        samples = []
        for _ in range(runs):
            name = uniq()
            t0 = time.perf_counter()
            spec(name, wins, panes).build(engine, preflight=False)
            samples.append((time.perf_counter() - t0) * 1000)
        return samples

    server = new_server()
    if impl.needs_preboot:
        server.cmd("start-server")
    engine = impl.make_engine(server) if impl.make_engine else None
    try:
        for _ in range(warmup):
            name = uniq()
            do_build(impl, server, engine, name, wins, panes)
            if wait:
                wait_ready(server, name)
            server.cmd("kill-session", "-t", name)
        samples = []
        for _ in range(runs):
            name = uniq()
            t0 = time.perf_counter()
            do_build(impl, server, engine, name, wins, panes)
            if wait:
                wait_ready(server, name)
            samples.append((time.perf_counter() - t0) * 1000)
            server.cmd("kill-session", "-t", name)  # untimed cleanup -> no accumulation
        return samples
    finally:
        with contextlib.suppress(Exception):
            server.kill()


# --------------------------------------------------------------------------- #
# Stats (nearest-rank percentiles, like agentgrep's benchmark)                #
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #
app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def run(
    shapes: str = typer.Option("1x1,1x4,3x3,5x4,8x4", help="comma WxP shapes"),
    engines: str = typer.Option(
        "classic,subprocess,control_mode,imsg,concrete,pipelined",
        help="comma engine names",
    ),
    wait: bool = typer.Option(False, help="ALSO measure with shell-readiness wait"),
    runs: int = typer.Option(20, help="timed builds per cell"),
    warmup: int = typer.Option(3, help="warmup builds per cell"),
    json_out: str = typer.Option("", help="write full JSON results here"),
) -> None:
    """In-process build-only benchmark grid (the clean signal)."""
    shape_list = [parse_shape(s) for s in shapes.split(",") if s]
    engine_list = [e for e in engines.split(",") if e in IMPLS]
    wait_modes = [False, True] if wait else [False]
    results: list[dict[str, t.Any]] = []

    for wm in wait_modes:
        for wins, panes in shape_list:
            table = rich.table.Table(
                title=f"[bold]{wins} win x {panes} pane  ({wins * panes} panes)"
                f"{'  [wait]' if wm else ''}  -- in-process build ms[/bold]"
            )
            table.add_column("engine", style="cyan")
            for label in STAT_LABELS:
                table.add_column(label, justify="right")
            table.add_column("vs classic", justify="right", style="green")
            base_median = None
            for name in engine_list:
                impl = IMPLS[name]
                if impl.kind == "offline" and wm:
                    continue  # no real panes to wait on
                samples = run_cell(impl, wins, panes, wm, runs, warmup)
                st = summarize(samples)
                if name == "classic":
                    base_median = st["median"]
                speed = (
                    f"{base_median / st['median']:.1f}x"
                    if base_median and st["median"]
                    else "-"
                )
                table.add_row(
                    name,
                    f"{int(st['n'])}",
                    *[f"{st[k]:.1f}" for k in STAT_LABELS[1:]],
                    speed,
                )
                results.append(
                    {
                        "engine": name,
                        "shape": f"{wins}x{panes}",
                        "panes": wins * panes,
                        "wait": wm,
                        "samples_ms": samples,
                        **{f"{k}_ms": st[k] for k in STAT_LABELS},
                    }
                )
            console.print(table)
            console.print()

    if json_out:
        pathlib.Path(json_out).write_text(json.dumps(results, indent=2))
        console.print(f"[dim]wrote {json_out}[/dim]")


@app.command()
def cell(engine: str, shape: str, wait: bool = typer.Option(False)) -> None:
    """Build ONE workspace of *shape* with *engine* (isolated). For hyperfine."""
    impl = IMPLS[engine]
    wins, panes = parse_shape(shape)
    if impl.kind == "offline":
        spec(uniq(), wins, panes).build(impl.make_engine(None), preflight=False)  # type: ignore[misc]
        return
    server = new_server()
    if impl.needs_preboot:
        server.cmd("start-server")
    eng = impl.make_engine(server) if impl.make_engine else None
    try:
        name = uniq()
        do_build(impl, server, eng, name, wins, panes)
        if wait:
            wait_ready(server, name)
    finally:
        with contextlib.suppress(Exception):
            server.kill()


@app.command()
def profile(
    engine: str = typer.Option("control_mode"),
    shape: str = typer.Option("8x4"),
    builds: int = typer.Option(5),
    top: int = typer.Option(18),
) -> None:
    """Profile *builds* builds of *shape* with *engine*; print slowest by cumtime."""
    impl = IMPLS[engine]
    wins, panes = parse_shape(shape)
    server = None if impl.kind == "offline" else new_server()
    if server is not None and impl.needs_preboot:
        server.cmd("start-server")
    eng = impl.make_engine(server) if impl.make_engine else None
    try:
        warm = uniq()
        do_build(impl, server, eng, warm, wins, panes)  # warmup
        if server is not None:
            server.cmd("kill-session", "-t", warm)
        pr = cProfile.Profile()
        pr.enable()
        for _ in range(builds):
            name = uniq()
            do_build(impl, server, eng, name, wins, panes)
            if server is not None:
                server.cmd("kill-session", "-t", name)
        pr.disable()
        buf = io.StringIO()
        pstats.Stats(pr, stream=buf).sort_stats("cumulative").print_stats(top)
        console.print(f"[bold]profile: {engine} {shape} x{builds}[/bold]")
        console.print(buf.getvalue())
    finally:
        if server is not None:
            with contextlib.suppress(Exception):
                server.kill()


if __name__ == "__main__":
    app()
