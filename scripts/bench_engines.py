#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["rich>=13", "typer>=0.12", "libtmux"]
#
# [tool.uv.sources]
# libtmux = { path = "..", editable = true }
# ///

# ``typer`` is a PEP 723 inline dependency, resolved only inside ``uv run``'s
# ephemeral venv; the repo's mypy environment can't import it, which also makes
# its command decorators look untyped. Suppress just those two environment
# artifacts -- every other check (including the ImsgForServer narrowing below)
# stays strict.
# mypy: disable-error-code="import-not-found, untyped-decorator"
"""Hermetic libtmux engine build-benchmark grid.

Measures how long the experimental workspace builder and the classic API take to
build tmux session structures, sweeping scenarios x engines x wait-modes.
Reports min/avg/median/max/p90/p95/p99. A separately named hand-written
no-capture pipeline remains available as an opt-in prototype; it is not a
planner comparison and does not participate in the parity contract.

Hermetic & sandboxed: every server runs on its OWN socket under a throwaway
mkdtemp dir; ``TMUX`` is unset at import so the ambient session is never touched;
an ``atexit`` hook kills every spawned server (and any orphan on our sockets) and
removes the dir. The default server is never contacted.

Engines (``--engines``):
  classic       classic libtmux Server/Session/Window/Pane API (subprocess)
  subprocess    builder on SubprocessEngine     (one tmux fork per op)
  control_mode  builder on ControlModeEngine    (one persistent ``tmux -C``)
  imsg          builder on ImsgEngine           (AF_UNIX imsg, socket-injected)
  mock          builder on MockEngine       (offline, in-memory: Python floor)
  prototype-pipelined
                hand-written no-capture run_batch prototype (opt-in only)

Timing: ``run`` measures in-process build-only latency. The ``cell`` subcommand
provides one whole-process build for external tools such as hyperfine.

The ``matrix`` subcommand isolates *why* a build costs what it does, sweeping a
four-axis factorial -- async {sync, async} x transport {subprocess,
control_mode} x planner {imperative, sequential, batching} x expression
{hand plan, declarative, workspace default}. The workload includes adjacent
ready operations, so sequential and batching planners have measurably different
step shapes while retaining identical tmux requests. The matrix reports observed
planner/request grouping separately from process-start models; unknown or
cache-dependent counts remain explicitly unmeasured. ``mock`` is the offline
correctness oracle.
``concurrency`` is an exploratory sync-serial versus ``asyncio.gather`` probe.
Its startup boundaries and strategy order are not symmetric, so it is not
evidence for async speed or event-loop health. tmux also serializes its server
command queue.

Run:  uv run bench_engines.py run
      uv run bench_engines.py run --engines control_mode,prototype-pipelined --wait
      uv run bench_engines.py profile --engine control_mode --shape 8x4
      uv run bench_engines.py cell control_mode 8x4
      uv run bench_engines.py matrix --shapes 1x1x4,1x4x1,4x1x1
      uv run bench_engines.py concurrency --transport control_mode --k 4
      uv run bench_engines.py contract
"""

from __future__ import annotations

import asyncio
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
    AsyncControlModeEngine,
    AsyncMockEngine,
    AsyncSubprocessEngine,
    ControlModeEngine,
    ImsgEngine,
    MockEngine,
    SubprocessEngine,
)
from libtmux.experimental.engines.base import CommandRequest
from libtmux.experimental.ops import (
    BatchingPlanner,
    LazyPlan,
    NewSession,
    NewWindow,
    Planner,
    RenameWindow,
    SequentialPlanner,
    SetOption,
    SplitWindow,
    arun as op_arun,
    run as op_run,
)
from libtmux.experimental.ops._types import PaneId, SessionId, SlotRef, WindowId
from libtmux.experimental.workspace import Pane, Window, Workspace
from libtmux.server import Server

console = rich.console.Console()
# Wide console for the factorial tables: their per-cell labels (layer · transport
# · mode) overflow an 80-col pipe, so render them at a fixed width so each row
# stays on one line under redirection.
wide_console = rich.console.Console(width=132)
R = CommandRequest.from_args
_ctr = itertools.count()
STAT_LABELS = ("n", "min", "avg", "median", "p90", "p95", "p99", "max")
BENCH_OPTIONS = (
    ("@libtmux_bench_one", "1"),
    ("@libtmux_bench_two", "2"),
)

# --------------------------------------------------------------------------- #
# Hermetic isolation                                                          #
# --------------------------------------------------------------------------- #
_SOCK_DIR = pathlib.Path(
    tempfile.mkdtemp(prefix="ltbench-")
)  # short: /tmp/ltbench-XXXX
_SERVERS: list[Server] = []
#: A session every bench server keeps for its whole life, so killing a cell's
#: session never drops the server to zero and trips tmux's exit-empty teardown.
_KEEPALIVE = "keepalive"


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
    """
    srv = Server(
        socket_path=str(_SOCK_DIR / f"{uuid.uuid4().hex[:8]}.sock"),
        config_file=os.devnull,
    )
    _SERVERS.append(srv)
    # The keepalive has to come first: `start-server` alone leaves a server with
    # zero sessions, which exits immediately under the default, so there is no
    # server left to set the option on. Creating a session that is never killed
    # is what actually holds the floor above zero.
    srv.cmd("new-session", "-d", "-s", _KEEPALIVE)
    srv.cmd("set-option", "-s", "exit-empty", "off")
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


def _reap_stale_scratch() -> None:
    """Remove scratch dirs left behind by runs that died before their cleanup.

    :func:`_cleanup` only knows *this* process's socket dir, so a run killed
    before its ``atexit`` hook leaves its dir -- and any tmux still bound to
    it -- behind for good. Those survivors keep consuming CPU and file
    descriptors, and machine load is precisely what makes the server-teardown
    race fire, so an unreaped leak feeds the very failure it came from.

    A dir with a live tmux is left alone: it may belong to a concurrent run, and
    stealing another run's servers would be worse than leaking. That means hung
    clients are only reclaimed once their server is gone, which is the
    conservative trade.
    """
    reaped = 0
    for path in pathlib.Path(tempfile.gettempdir()).glob("ltbench-*"):
        if path == _SOCK_DIR or not path.is_dir():
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
    if reaped:
        console.print(f"[dim]reaped {reaped} stale bench scratch dir(s)[/dim]")


atexit.register(_cleanup)
_reap_stale_scratch()


def uniq() -> str:
    """Return a process-unique session name (never collides across builds)."""
    return f"b{next(_ctr)}"


# --------------------------------------------------------------------------- #
# Scenario spec + build implementations                                       #
# --------------------------------------------------------------------------- #
@dataclasses.dataclass(frozen=True)
class Scenario:
    """One benchmark sample's session/window/pane cardinality.

    Attributes
    ----------
    sessions : int
        Independent sessions built sequentially per timed sample.
    windows : int
        Windows created in each session.
    panes : int
        Tiled panes created in each window.
    """

    sessions: int
    windows: int
    panes: int

    @property
    def label(self) -> str:
        """Return the canonical ``SxWxP`` label.

        >>> Scenario(2, 3, 4).label
        '2x3x4'
        """
        return f"{self.sessions}x{self.windows}x{self.panes}"


def parse_scenario(value: str) -> Scenario:
    """Parse ``WxP`` or ``SxWxP`` cardinality into a scenario.

    >>> parse_scenario("8x4")
    Scenario(sessions=1, windows=8, panes=4)
    >>> parse_scenario("2x3x4")
    Scenario(sessions=2, windows=3, panes=4)
    """
    parts = value.lower().split("x")
    if len(parts) == 2:
        parts.insert(0, "1")
    if len(parts) != 3:
        msg = f"expected WxP or SxWxP, got {value!r}"
        raise ValueError(msg)
    sessions, windows, panes = (int(part) for part in parts)
    if min(sessions, windows, panes) < 1:
        msg = f"scenario dimensions must be positive, got {value!r}"
        raise ValueError(msg)
    return Scenario(sessions, windows, panes)


def parse_shape(value: str) -> tuple[int, int]:
    """Parse a one-session ``WxP`` shape for single-session commands.

    >>> parse_shape("8x4")
    (8, 4)
    """
    scenario = parse_scenario(value)
    if scenario.sessions != 1:
        msg = f"this command accepts WxP only, got {value!r}"
        raise ValueError(msg)
    return scenario.windows, scenario.panes


def parse_scenarios(value: str) -> list[Scenario]:
    """Parse a comma-separated scenario option or raise a CLI usage error.

    >>> parse_scenarios("1x1,2x3x4")
    [Scenario(sessions=1, windows=1, panes=1), Scenario(sessions=2, windows=3, panes=4)]
    """
    try:
        scenarios = [parse_scenario(item) for item in value.split(",") if item]
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--shapes") from error
    if not scenarios:
        msg = "at least one scenario is required"
        raise typer.BadParameter(msg, param_hint="--shapes")
    return scenarios


def _select_axis(
    value: str,
    choices: t.Collection[str],
    option: str,
) -> list[str]:
    """Parse a comma-separated matrix axis without silently dropping values."""
    selected = [item.strip() for item in value.split(",") if item.strip()]
    available = set(choices)
    unknown = [item for item in selected if item not in available]
    if unknown:
        expected = ", ".join(sorted(available))
        msg = f"unknown value(s) {', '.join(unknown)}; choose from {expected}"
        raise typer.BadParameter(msg, param_hint=option)
    if not selected:
        msg = "at least one value is required"
        raise typer.BadParameter(msg, param_hint=option)
    return selected


def spec(name: str, wins: int, panes: int) -> Workspace:
    """Build the declarative Workspace IR for *wins* windows x *panes* panes."""
    return Workspace(
        name=name,
        on_exists="replace",
        options=dict(BENCH_OPTIONS),
        windows=[
            Window(name=f"w{w}", panes=[Pane() for _ in range(panes)])
            for w in range(wins)
        ],
    )


def build_classic(server: Server, name: str, wins: int, panes: int) -> None:
    """Build the structure with the classic Server/Session/Window/Pane API."""
    session = server.new_session(session_name=name, window_name="w0")
    for option, value in BENCH_OPTIONS:
        session.set_option(option, value)
    for _ in range(panes - 1):
        session.active_window.split()
    for wi in range(1, wins):
        window = session.new_window(window_name=f"w{wi}")
        for _ in range(panes - 1):
            window.split()


def build_pipelined(engine: t.Any, name: str, wins: int, panes: int) -> None:
    """Prototype: batch independent named targets without capturing ids.

    This is deliberately outside the planner comparison. It hand-writes tmux
    argv, targets objects by chosen names, and does not provide the per-operation
    captured-id contract of the typed plan/workspace paths.
    """
    engine.run(R("new-session", "-d", "-s", name, "-n", "w0"))
    ready = [
        R("set-option", "-t", name, "--", option, value)
        for option, value in BENCH_OPTIONS
    ]
    ready.extend(R("new-window", "-t", name, "-n", f"w{i}") for i in range(1, wins))
    engine.run_batch(ready)
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

    def __init__(self, server: Server | None) -> None:
        assert server is not None
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
    kind: str  # classic | builder | prototype-pipelined | offline
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
    "mock": Impl("mock", "offline", lambda s: MockEngine(), preflight=False),
    "prototype-pipelined": Impl(
        "prototype-pipelined",
        "prototype-pipelined",
        lambda s: ControlModeEngine.for_server(s),
    ),
}


def do_build(
    impl: Impl, server: Server | None, engine: t.Any, name: str, w: int, p: int
) -> None:
    """Dispatch one build of *w* x *p* to the right implementation path."""
    if impl.kind == "classic":
        build_classic(server, name, w, p)  # type: ignore[arg-type]
    elif impl.kind == "prototype-pipelined":
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


def _checked_stdout(server: Server, *args: str) -> tuple[str, ...]:
    """Run a diagnostic tmux query and reject transport or tmux failures."""
    result = server.cmd(*args)
    if result.returncode != 0:
        detail = " ".join(result.stderr) or f"tmux exited {result.returncode}"
        msg = f"benchmark verification command failed: {' '.join(args)}: {detail}"
        raise RuntimeError(msg)
    return tuple(result.stdout)


def _kill_session(server: Server, name: str) -> None:
    """Remove a benchmark session and reject cleanup failures."""
    _checked_stdout(server, "kill-session", "-t", name)


def verify_topology(
    server: Server,
    names: t.Sequence[str],
    *,
    windows: int,
    panes: int,
) -> None:
    """Reject a partial or semantically wrong live benchmark sample."""
    live_sessions = set(
        _checked_stdout(server, "list-sessions", "-F", "#{session_name}")
    )
    missing = [name for name in names if name not in live_sessions]
    if missing:
        msg = f"missing benchmark sessions: {', '.join(missing)}"
        raise RuntimeError(msg)
    expected_window_names = {f"w{index}" for index in range(windows)}
    for name in names:
        window_names = set(
            _checked_stdout(
                server,
                "list-windows",
                "-t",
                name,
                "-F",
                "#{window_name}",
            )
        )
        if window_names != expected_window_names:
            msg = (
                f"{name}: expected windows {sorted(expected_window_names)!r}, "
                f"got {sorted(window_names)!r}"
            )
            raise RuntimeError(msg)
        pane_ids = _checked_stdout(
            server,
            "list-panes",
            "-s",
            "-t",
            name,
            "-F",
            "#{pane_id}",
        )
        expected_panes = windows * panes
        if len(pane_ids) != expected_panes:
            msg = f"{name}: expected {expected_panes} panes, got {len(pane_ids)}"
            raise RuntimeError(msg)
        for option, expected in BENCH_OPTIONS:
            actual = _checked_stdout(
                server,
                "show-options",
                "-t",
                name,
                "-v",
                option,
            )
            if actual != (expected,):
                msg = f"{name}: expected {option}={expected!r}, got {actual!r}"
                raise RuntimeError(msg)


def run_cell(
    impl: Impl,
    wins: int,
    panes: int,
    wait: bool,
    runs: int,
    warmup: int,
    sessions: int = 1,
) -> list[float]:
    """Return per-sample wall times with *sessions* sequential builds each."""
    if impl.kind == "offline":
        engine = impl.make_engine(None)  # type: ignore[misc]
        for _ in range(warmup):
            for _ in range(sessions):
                spec(uniq(), wins, panes).build(engine, preflight=False)
        samples = []
        for _ in range(runs):
            names = [uniq() for _ in range(sessions)]
            t0 = time.perf_counter()
            for name in names:
                spec(name, wins, panes).build(engine, preflight=False)
            samples.append((time.perf_counter() - t0) * 1000)
        return samples

    server = new_server()
    if impl.needs_preboot:
        server.cmd("start-server")
    engine = impl.make_engine(server) if impl.make_engine else None
    try:
        for _ in range(warmup):
            names = [uniq() for _ in range(sessions)]
            for name in names:
                do_build(impl, server, engine, name, wins, panes)
                if wait:
                    wait_ready(server, name)
            verify_topology(server, names, windows=wins, panes=panes)
            for name in names:
                _kill_session(server, name)
        samples = []
        for _ in range(runs):
            names = [uniq() for _ in range(sessions)]
            t0 = time.perf_counter()
            for name in names:
                do_build(impl, server, engine, name, wins, panes)
                if wait:
                    wait_ready(server, name)
            samples.append((time.perf_counter() - t0) * 1000)
            verify_topology(server, names, windows=wins, panes=panes)
            for name in names:
                _kill_session(server, name)
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


def summary_json(summary: dict[str, float]) -> dict[str, float | int]:
    """Return JSON field names with a unit only on duration values.

    >>> summary_json({"n": 2.0, "min": 1.5})
    {'n': 2, 'min_ms': 1.5}
    """
    return {
        "n": int(summary["n"]),
        **{f"{name}_ms": summary[name] for name in STAT_LABELS[1:] if name in summary},
    }


# --------------------------------------------------------------------------- #
# Factorial matrix -- axes as registries, the grid via itertools.product       #
# --------------------------------------------------------------------------- #
# Three orthogonal axes, each its own small registry. The matrix is *generated*
# by product() over them, never enumerated by hand -- adding an axis value (a new
# transport, a new expression layer) is one registry entry, and every cell flows
# through one generic timing core.
#
#   MODES       sync | async                -- which run-strategy drives a build
#   TRANSPORTS  subprocess | control_mode   -- each supplies a sync + async engine
#   LAYERS      imperative | plan-seq | plan-batch | ws-seq | ws-batch | default
#
# A declarative Workspace compiles to a LazyPlan, so ws-* and plan-* share one op
# spine. ``default`` exercises Workspace's public default instead of spelling a
# planner explicitly. `mock` is NOT a layer -- it is the offline correctness
# oracle for the parity contract (`check_parity`), never a results row.
#
# Sync/async is unified without contaminating either path with the other's
# machinery: the plan/ws layers differ only by method name (`execute`/`aexecute`,
# `build`/`abuild`), and the imperative layer is a single sans-I/O generator of
# ops -- a sync pump drives it with `run`, an async pump with `arun`. That is the
# same colored-leaf split the library's own ``LazyPlan._drive`` uses.

MODES: tuple[str, ...] = ("sync", "async")


def _imperative_ops(
    name: str, wins: int, panes: int
) -> t.Generator[t.Any, t.Any, None]:
    """Yield the WxP build as typed ops, reading each created id off its result.

    A sans-I/O generator: it ``yield``s an operation and is ``.send()`` the typed
    result, from which it reads the concrete id to target the next op. Written
    ONCE; :func:`_pump_sync` drives it with :func:`op_run`, :func:`_pump_async`
    with :func:`op_arun`. The emitted op sequence mirrors the workspace compiler
    exactly, so it renders argv-identical to every other layer under mock.
    """
    result = yield NewSession(session_name=name, capture_panes=True)
    session_id, window0_id, pane0_id = (
        result.new_id,
        result.first_window_id,
        result.first_pane_id,
    )
    for option, value in BENCH_OPTIONS:
        yield SetOption(
            target=SessionId(session_id),
            option=option,
            value=value,
        )
    yield RenameWindow(target=WindowId(window0_id), name="w0")
    prev = pane0_id
    for _ in range(panes - 1):
        result = yield SplitWindow(target=PaneId(prev))
        prev = result.new_pane_id
    for wi in range(1, wins):
        result = yield NewWindow(
            target=SessionId(session_id), name=f"w{wi}", capture_pane=True
        )
        prev = result.first_pane_id
        for _ in range(panes - 1):
            result = yield SplitWindow(target=PaneId(prev))
            prev = result.new_pane_id


def _pump_sync(gen: t.Generator[t.Any, t.Any, None], engine: t.Any) -> None:
    """Drive an op-generator synchronously (``run`` one op, send its result back)."""
    try:
        op = next(gen)
        while True:
            result = op_run(op, engine).raise_for_status()
            op = gen.send(result)
    except StopIteration:
        pass


async def _pump_async(gen: t.Generator[t.Any, t.Any, None], engine: t.Any) -> None:
    """Async twin of :func:`_pump_sync` (``await arun`` per op)."""
    try:
        op = next(gen)
        while True:
            result = (await op_arun(op, engine)).raise_for_status()
            op = gen.send(result)
    except StopIteration:
        pass


def _hand_plan(name: str, wins: int, panes: int) -> LazyPlan:
    """Hand-author the WxP build as a ``LazyPlan`` with forward SlotRef targets.

    Mirrors :func:`_imperative_ops` (and the workspace compiler) op-for-op, but
    records refs instead of resolving ids eagerly, so a planner can batch or
    sequence the execution steps.
    """
    plan = LazyPlan()
    session = plan.add(NewSession(session_name=name, capture_panes=True))
    for option, value in BENCH_OPTIONS:
        plan.add(SetOption(target=session, option=option, value=value))
    plan.add(RenameWindow(target=session.window, name="w0"))
    prev: SlotRef = session.pane
    for _ in range(panes - 1):
        prev = plan.add(SplitWindow(target=prev))
    for wi in range(1, wins):
        window = plan.add(NewWindow(target=session, name=f"w{wi}", capture_pane=True))
        prev = window.pane
        for _ in range(panes - 1):
            prev = plan.add(SplitWindow(target=prev))
    return plan


@dataclasses.dataclass(frozen=True)
class Layer:
    """One expression layer: how a build is authored and planned.

    ``kind`` selects the execution shape (``imperative`` drives the generator;
    ``plan`` executes a hand ``LazyPlan``; ``ws`` builds the declarative
    :class:`~libtmux.experimental.workspace.Workspace` IR). ``planner`` is the
    step-grouping policy for the plan/ws kinds. ``None`` means no planner for
    imperative and the public default for ``default``.
    """

    name: str
    kind: str  # imperative | plan | ws
    planner: Planner | None = None


LAYERS: dict[str, Layer] = {
    "imperative": Layer("imperative", "imperative"),
    "plan-seq": Layer("plan-seq", "plan", SequentialPlanner()),
    "plan-batch": Layer("plan-batch", "plan", BatchingPlanner()),
    "ws-seq": Layer("ws-seq", "ws", SequentialPlanner()),
    "ws-batch": Layer("ws-batch", "ws", BatchingPlanner()),
    "default": Layer("default", "ws"),
}


def build_sync(layer: Layer, engine: t.Any, name: str, wins: int, panes: int) -> None:
    """Execute one WxP build for *layer* over a synchronous *engine*."""
    if layer.kind == "imperative":
        _pump_sync(_imperative_ops(name, wins, panes), engine)
    elif layer.kind == "plan":
        _hand_plan(name, wins, panes).execute(
            engine, planner=layer.planner
        ).raise_for_status()
    else:  # ws
        spec(name, wins, panes).build(
            engine, preflight=False, planner=layer.planner
        ).raise_for_status()


async def build_async(
    layer: Layer, engine: t.Any, name: str, wins: int, panes: int
) -> None:
    """Execute one WxP build for *layer* over an asynchronous *engine*."""
    if layer.kind == "imperative":
        await _pump_async(_imperative_ops(name, wins, panes), engine)
    elif layer.kind == "plan":
        outcome = await _hand_plan(name, wins, panes).aexecute(
            engine, planner=layer.planner
        )
        outcome.raise_for_status()
    else:  # ws
        outcome = await spec(name, wins, panes).abuild(
            engine, preflight=False, planner=layer.planner
        )
        outcome.raise_for_status()


@dataclasses.dataclass(frozen=True)
class Transport:
    """One transport axis value: a sync engine factory and an async one."""

    name: str
    make_sync: t.Callable[[Server], t.Any]
    make_async: t.Callable[[Server], t.Any]


TRANSPORTS: dict[str, Transport] = {
    "subprocess": Transport(
        "subprocess",
        lambda s: SubprocessEngine.for_server(s),
        lambda s: AsyncSubprocessEngine.for_server(s),
    ),
    "control_mode": Transport(
        "control_mode",
        lambda s: ControlModeEngine.for_server(s),
        lambda s: AsyncControlModeEngine.for_server(s),
    ),
}


@contextlib.asynccontextmanager
async def _open_async(transport: Transport, server: Server) -> t.AsyncIterator[t.Any]:
    """Yield an async engine, honoring an async context manager when it is one.

    ``AsyncControlModeEngine`` holds a persistent connection (opened on enter,
    closed on exit); ``AsyncSubprocessEngine`` is per-call and needs no teardown.
    """
    engine = transport.make_async(server)
    if hasattr(engine, "__aenter__"):
        async with engine as opened:
            yield opened
    else:
        yield engine


def _sync_cell(
    transport: Transport,
    layer: Layer,
    server: Server,
    wins: int,
    panes: int,
    sessions: int,
    runs: int,
    warmup: int,
) -> list[float]:
    """Time *runs* synchronous builds of one cell (untimed kill-session cleanup)."""
    engine = transport.make_sync(server)
    for _ in range(warmup):
        names = [uniq() for _ in range(sessions)]
        for name in names:
            build_sync(layer, engine, name, wins, panes)
            verify_topology(server, names, windows=wins, panes=panes)
            for name in names:
                _kill_session(server, name)
    samples: list[float] = []
    for _ in range(runs):
        names = [uniq() for _ in range(sessions)]
        t0 = time.perf_counter()
        for name in names:
            build_sync(layer, engine, name, wins, panes)
        samples.append((time.perf_counter() - t0) * 1000)
        verify_topology(server, names, windows=wins, panes=panes)
        for name in names:
            _kill_session(server, name)
    return samples


async def _akill_session(server: Server, name: str) -> None:
    """Kill *name* without blocking the event loop.

    ``server.cmd`` shells out synchronously. Called straight from a coroutine it
    stalls the loop mid-cell, and a blocking subprocess issued from inside a
    running loop measurably raises the rate of failed ``new-session`` calls, so
    the cleanup is offloaded to a thread.
    """
    await asyncio.to_thread(_kill_session, server, name)


async def _async_cell(
    transport: Transport,
    layer: Layer,
    server: Server,
    wins: int,
    panes: int,
    sessions: int,
    runs: int,
    warmup: int,
) -> list[float]:
    """Async twin of :func:`_sync_cell`, over one persistent async connection."""
    async with _open_async(transport, server) as engine:
        for _ in range(warmup):
            names = [uniq() for _ in range(sessions)]
            for name in names:
                await build_async(layer, engine, name, wins, panes)
            await asyncio.to_thread(
                verify_topology, server, names, windows=wins, panes=panes
            )
            for name in names:
                await _akill_session(server, name)
        samples: list[float] = []
        for _ in range(runs):
            names = [uniq() for _ in range(sessions)]
            t0 = time.perf_counter()
            for name in names:
                await build_async(layer, engine, name, wins, panes)
            samples.append((time.perf_counter() - t0) * 1000)
            await asyncio.to_thread(
                verify_topology, server, names, windows=wins, panes=panes
            )
            for name in names:
                await _akill_session(server, name)
        return samples


def matrix_cell(
    transport: Transport,
    mode: str,
    layer: Layer,
    wins: int,
    panes: int,
    sessions: int,
    runs: int,
    warmup: int,
) -> list[float]:
    """Time one generated cell (transport x mode x layer) on a fresh server."""
    server = new_server()
    try:
        if mode == "sync":
            return _sync_cell(
                transport, layer, server, wins, panes, sessions, runs, warmup
            )
        return asyncio.run(
            _async_cell(transport, layer, server, wins, panes, sessions, runs, warmup)
        )
    finally:
        with contextlib.suppress(Exception):
            server.kill()


# --------------------------------------------------------------------------- #
# Mock-parity contract: every layer x mode renders the SAME argv as mock        #
# --------------------------------------------------------------------------- #
@dataclasses.dataclass(frozen=True)
class RecordedBuild:
    """One mock build's exact requests and engine-call grouping."""

    argv: tuple[tuple[str, ...], ...]
    batch_sizes: tuple[int, ...]

    @property
    def tmux_requests(self) -> int:
        """Return the number of distinct tmux requests."""
        return len(self.argv)

    @property
    def engine_calls(self) -> int:
        """Return the number of ``run``/``run_batch`` engine calls."""
        return len(self.batch_sizes)


@dataclasses.dataclass(frozen=True)
class ExecutionShape:
    """Transport-independent execution shape for one expression layer."""

    planner_steps: int | None
    engine_calls: int
    tmux_requests: int
    batch_sizes: tuple[int, ...]


class _Recorder:
    """Wrap a sync engine, recording requests and engine-call grouping."""

    def __init__(self, inner: t.Any) -> None:
        self.inner = inner
        self.argv: list[tuple[str, ...]] = []
        self.batch_sizes: list[int] = []

    def run(self, request: CommandRequest) -> t.Any:
        """Record and forward one request."""
        self.argv.append(tuple(request.args))
        self.batch_sizes.append(1)
        return self.inner.run(request)

    def run_batch(self, requests: t.Sequence[CommandRequest]) -> t.Any:
        """Record and forward a batch of requests."""
        self.argv.extend(tuple(r.args) for r in requests)
        self.batch_sizes.append(len(requests))
        return self.inner.run_batch(requests)


class _AsyncRecorder:
    """Async twin of :class:`_Recorder`."""

    def __init__(self, inner: t.Any) -> None:
        self.inner = inner
        self.argv: list[tuple[str, ...]] = []
        self.batch_sizes: list[int] = []

    async def run(self, request: CommandRequest) -> t.Any:
        """Record and forward one request."""
        self.argv.append(tuple(request.args))
        self.batch_sizes.append(1)
        return await self.inner.run(request)

    async def run_batch(self, requests: t.Sequence[CommandRequest]) -> t.Any:
        """Record and forward a batch of requests."""
        self.argv.extend(tuple(r.args) for r in requests)
        self.batch_sizes.append(len(requests))
        return await self.inner.run_batch(requests)


def _record_sync(layer: Layer, name: str, wins: int, panes: int) -> RecordedBuild:
    """Render *layer* through MockEngine, recording requests and grouping."""
    recorder = _Recorder(MockEngine())
    build_sync(layer, recorder, name, wins, panes)
    return RecordedBuild(tuple(recorder.argv), tuple(recorder.batch_sizes))


async def _record_async(
    layer: Layer, name: str, wins: int, panes: int
) -> RecordedBuild:
    """Async twin of :func:`_record_sync` (AsyncMockEngine)."""
    recorder = _AsyncRecorder(AsyncMockEngine())
    await build_async(layer, recorder, name, wins, panes)
    return RecordedBuild(tuple(recorder.argv), tuple(recorder.batch_sizes))


def execution_shape(layer: Layer, wins: int, panes: int) -> ExecutionShape:
    """Return exact planner-step and request counts for one mock build."""
    recorded = _record_sync(layer, "shape", wins, panes)
    return ExecutionShape(
        planner_steps=(recorded.engine_calls if layer.kind != "imperative" else None),
        engine_calls=recorded.engine_calls,
        tmux_requests=recorded.tmux_requests,
        batch_sizes=recorded.batch_sizes,
    )


def batch_size_summary(sizes: tuple[int, ...]) -> str:
    """Format adjacent equal batch sizes with run-length encoding.

    >>> batch_size_summary((1, 1, 3, 1))
    '1x2,3,1'
    """
    parts: list[str] = []
    for size, run in itertools.groupby(sizes):
        count = sum(1 for _ in run)
        parts.append(str(size) if count == 1 else f"{size}x{count}")
    return ",".join(parts)


def check_parity(
    wins: int, panes: int
) -> tuple[list[tuple[str, ...]], list[tuple[str, bool]]]:
    """Assert every layer x mode renders the mock oracle's argv for WxP.

    Mock is deterministic, so every expression layer -- driven through it via
    both the sync and async paths -- must emit the identical op argv sequence.
    The oracle is the declarative ws-seq rendering (one argv per op); returns the
    oracle plus a ``(label, agrees)`` row per layer x mode.
    """
    name = "parity"
    oracle = _record_sync(LAYERS["ws-seq"], name, wins, panes).argv
    rows: list[tuple[str, bool]] = []
    for layer_name, layer in LAYERS.items():
        sync_record = _record_sync(layer, name, wins, panes)
        rows.append((f"{layer_name}/sync", sync_record.argv == oracle))
        async_record = asyncio.run(_record_async(layer, name, wins, panes))
        rows.append(
            (
                f"{layer_name}/async",
                async_record.argv == oracle
                and async_record.batch_sizes == sync_record.batch_sizes,
            )
        )
    return list(oracle), rows


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #
app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def run(
    shapes: str = typer.Option("1x1,1x4,3x3,5x4,8x4", help="comma WxP shapes"),
    engines: str = typer.Option(
        "classic,subprocess,control_mode,imsg,mock",
        help="comma engine names; prototype-pipelined is opt-in",
    ),
    wait: bool = typer.Option(False, help="ALSO measure with shell-readiness wait"),
    runs: int = typer.Option(20, help="timed builds per cell"),
    warmup: int = typer.Option(3, help="warmup builds per cell"),
    json_out: str = typer.Option("", help="write full JSON results here"),
) -> None:
    """In-process build-only benchmark grid (the clean signal)."""
    shape_list = [parse_shape(s) for s in shapes.split(",") if s]
    engine_list = _select_axis(engines, IMPLS, "--engines")
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
            table.add_column("vs legacy workflow", justify="right", style="green")
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
    """Build one isolated workspace for whole-process timing tools."""
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
            _kill_session(server, warm)
        pr = cProfile.Profile()
        pr.enable()
        for _ in range(builds):
            name = uniq()
            do_build(impl, server, eng, name, wins, panes)
            if server is not None:
                _kill_session(server, name)
        pr.disable()
        buf = io.StringIO()
        pstats.Stats(pr, stream=buf).sort_stats("cumulative").print_stats(top)
        console.print(f"[bold]profile: {engine} {shape} x{builds}[/bold]")
        console.print(buf.getvalue())
    finally:
        if server is not None:
            with contextlib.suppress(Exception):
                server.kill()


@app.command()
def matrix(
    shapes: str = typer.Option("1x4", help="comma WxP or SxWxP scenarios"),
    layers: str = typer.Option(",".join(LAYERS), help="comma expression layers"),
    transports: str = typer.Option(",".join(TRANSPORTS), help="comma transports"),
    modes: str = typer.Option("sync,async", help="comma modes: sync,async"),
    runs: int = typer.Option(100, help="timed samples per cell"),
    warmup: int = typer.Option(2, help="warmup builds per cell"),
    check: bool = typer.Option(True, help="run the mock-parity contract first"),
    json_out: str = typer.Option("", help="write full JSON results here"),
) -> None:
    """Factorial matrix: expression-layer x transport x mode per SxWxP scenario.

    Rows are *generated* by ``product`` over the axis registries (never
    hand-enumerated); ``classic`` is the reference row and ``mock`` never appears
    (it is the parity oracle, run first when ``--check``). Separate tables keep
    directly observed request grouping, process-start models, and elapsed time
    distinct.
    """
    scenarios = parse_scenarios(shapes)
    layer_list = _select_axis(layers, LAYERS, "--layers")
    transport_list = _select_axis(transports, TRANSPORTS, "--transports")
    mode_list = _select_axis(modes, MODES, "--modes")
    results: list[dict[str, t.Any]] = []

    for scenario in scenarios:
        sessions, wins, panes = (
            scenario.sessions,
            scenario.windows,
            scenario.panes,
        )
        if check:
            _oracle, parity_rows = check_parity(wins, panes)
            failed = [label for label, agrees in parity_rows if not agrees]
            if failed:
                console.print(
                    f"[bold red]mock-parity FAILED[/bold red] for {scenario.label}: "
                    f"{', '.join(failed)}"
                )
                raise typer.Exit(1)
            console.print(
                f"[green]mock-parity OK[/green] -- {len(parity_rows)} layer x mode "
                f"agree with mock argv for {scenario.label}"
            )

        structure = rich.table.Table(
            title=f"[bold]{scenario.label} execution shape (per sample)[/bold]"
        )
        structure.add_column("layer", style="cyan")
        structure.add_column("planner steps", justify="right")
        structure.add_column("engine calls", justify="right")
        structure.add_column("tmux requests", justify="right")
        structure.add_column("batch sizes (RLE)", justify="right")
        layer_shapes: dict[str, ExecutionShape] = {}
        for layer_name in layer_list:
            shape = execution_shape(LAYERS[layer_name], wins, panes)
            layer_shapes[layer_name] = shape
            batch_summary = batch_size_summary(shape.batch_sizes)
            if sessions > 1:
                batch_summary = f"({batch_summary}) x {sessions} sessions"
            structure.add_row(
                layer_name,
                (
                    str(shape.planner_steps * sessions)
                    if shape.planner_steps is not None
                    else "-"
                ),
                str(shape.engine_calls * sessions),
                str(shape.tmux_requests * sessions),
                batch_summary,
            )
        wide_console.print(structure)
        wide_console.print()

        process_model = rich.table.Table(
            title=(
                f"[bold]{scenario.label} process-start model (not instrumented)[/bold]"
            )
        )
        process_model.add_column("cell", style="cyan")
        process_model.add_column("command subprocesses/sample")
        process_model.add_column("version probes/cell")
        process_model.add_column("persistent clients/cell")
        for layer_name, transport_name in itertools.product(layer_list, transport_list):
            shape = layer_shapes[layer_name]
            if transport_name == "subprocess":
                command_model = f"{shape.tmux_requests * sessions} (exact: one/request)"
                persistent_model = "0 (engine model)"
            else:
                command_model = "? (bootstrap-dependent)"
                persistent_model = "<=1 (engine model; unmeasured)"
            process_model.add_row(
                f"{layer_name} · {transport_name}",
                command_model,
                "? (cache-dependent)",
                persistent_model,
            )
        wide_console.print(process_model)
        wide_console.print()

        classic_samples = run_cell(
            IMPLS["classic"], wins, panes, False, runs, warmup, sessions
        )
        base_median = summarize(classic_samples)["median"]

        table = rich.table.Table(
            title=f"[bold]{scenario.label} ({sessions} sessions, "
            f"{wins * sessions} windows, {wins * panes * sessions} panes)"
            f"  -- in-process build ms (async x transport x layer)[/bold]"
        )
        table.add_column("cell", style="cyan")
        for label in STAT_LABELS:
            table.add_column(label, justify="right")
        table.add_column("vs legacy workflow", justify="right", style="green")

        classic_stat = summarize(classic_samples)
        table.add_row(
            "classic (reference)",
            f"{int(classic_stat['n'])}",
            *[f"{classic_stat[k]:.1f}" for k in STAT_LABELS[1:]],
            "1.0x",
        )
        results.append(
            {
                "cell": "classic",
                "layer": "classic",
                "transport": "classic",
                "mode": "sync",
                "shape": f"{wins}x{panes}",
                "scenario": scenario.label,
                "sessions": sessions,
                "windows_per_session": wins,
                "panes_per_window": panes,
                "total_windows": wins * sessions,
                "total_panes": wins * panes * sessions,
                "panes": wins * panes * sessions,
                "planner_steps_per_session": None,
                "planner_steps": None,
                "engine_calls_per_session": None,
                "engine_calls": None,
                "tmux_requests_per_session": None,
                "tmux_requests": None,
                "batch_sizes_per_session": None,
                "batch_sizes": None,
                "command_subprocess_starts_per_sample": None,
                "command_subprocess_starts_basis": "unmeasured",
                "version_probe_subprocesses_per_cell": None,
                "version_probe_subprocesses_basis": "unmeasured",
                "persistent_tmux_clients_per_cell": None,
                "persistent_tmux_clients_basis": "unmeasured",
                "samples_ms": classic_samples,
                **summary_json(classic_stat),
            }
        )

        for layer_name, transport_name, mode in itertools.product(
            layer_list, transport_list, mode_list
        ):
            samples = matrix_cell(
                TRANSPORTS[transport_name],
                mode,
                LAYERS[layer_name],
                wins,
                panes,
                sessions,
                runs,
                warmup,
            )
            st = summarize(samples)
            shape = layer_shapes[layer_name]
            if transport_name == "subprocess":
                command_subprocess_starts: int | None = shape.tmux_requests * sessions
                command_subprocess_starts_basis = "exact-one-per-request"
                persistent_client_count: int | None = 0
                persistent_clients_basis = "engine-model-no-persistent-client"
            else:
                command_subprocess_starts = None
                command_subprocess_starts_basis = "bootstrap-dependent-unmeasured"
                persistent_client_count = None
                persistent_clients_basis = "at-most-one-engine-model-unmeasured"
            speed = (
                f"{base_median / st['median']:.1f}x"
                if base_median and st["median"]
                else "-"
            )
            label = f"{layer_name} · {transport_name} · {mode}"
            table.add_row(
                label,
                f"{int(st['n'])}",
                *[f"{st[k]:.1f}" for k in STAT_LABELS[1:]],
                speed,
            )
            results.append(
                {
                    "cell": label,
                    "layer": layer_name,
                    "transport": transport_name,
                    "mode": mode,
                    "shape": f"{wins}x{panes}",
                    "scenario": scenario.label,
                    "sessions": sessions,
                    "windows_per_session": wins,
                    "panes_per_window": panes,
                    "total_windows": wins * sessions,
                    "total_panes": wins * panes * sessions,
                    "panes": wins * panes * sessions,
                    "planner_steps_per_session": shape.planner_steps,
                    "planner_steps": (
                        shape.planner_steps * sessions
                        if shape.planner_steps is not None
                        else None
                    ),
                    "engine_calls_per_session": shape.engine_calls,
                    "engine_calls": shape.engine_calls * sessions,
                    "tmux_requests_per_session": shape.tmux_requests,
                    "tmux_requests": shape.tmux_requests * sessions,
                    "batch_sizes_per_session": shape.batch_sizes,
                    "batch_sizes": shape.batch_sizes * sessions,
                    "command_subprocess_starts_per_sample": command_subprocess_starts,
                    "command_subprocess_starts_basis": command_subprocess_starts_basis,
                    "version_probe_subprocesses_per_cell": None,
                    "version_probe_subprocesses_basis": "cache-dependent-unmeasured",
                    "persistent_tmux_clients_per_cell": persistent_client_count,
                    "persistent_tmux_clients_basis": persistent_clients_basis,
                    "samples_ms": samples,
                    **summary_json(st),
                }
            )

        wide_console.print(table)
        wide_console.print()

    if json_out:
        pathlib.Path(json_out).write_text(json.dumps(results, indent=2))
        console.print(f"[dim]wrote {json_out}[/dim]")


def _serial_build(
    transport: Transport, layer: Layer, server: Server, k: int, wins: int, panes: int
) -> float:
    """Build *k* independent sessions serially over a sync engine; return ms."""
    engine = transport.make_sync(server)
    names = [uniq() for _ in range(k)]
    t0 = time.perf_counter()
    for name in names:
        build_sync(layer, engine, name, wins, panes)
    elapsed = (time.perf_counter() - t0) * 1000
    verify_topology(server, names, windows=wins, panes=panes)
    for name in names:
        _kill_session(server, name)
    return elapsed


async def _gather_build(
    transport: Transport, layer: Layer, server: Server, k: int, wins: int, panes: int
) -> float:
    """Build *k* independent sessions via ``asyncio.gather`` over one connection."""
    async with _open_async(transport, server) as engine:
        names = [uniq() for _ in range(k)]
        t0 = time.perf_counter()
        await asyncio.gather(
            *(build_async(layer, engine, name, wins, panes) for name in names)
        )
        elapsed = (time.perf_counter() - t0) * 1000
        await asyncio.to_thread(
            verify_topology, server, names, windows=wins, panes=panes
        )
        for name in names:
            await _akill_session(server, name)
        return elapsed


@app.command()
def contract(
    shapes: str = typer.Option(
        "1x1x1,1x1x4,1x4x1,4x1x1,1x2x2",
        help="comma WxP or SxWxP scenarios",
    ),
) -> None:
    """Run the mock-parity contract standalone; exit non-zero on divergence.

    The benchmark's correctness oracle without the timing -- for CI, which can
    assert the ops language stays consistent without paying for live builds.
    Every expression layer, sync and async, must render the mock oracle's argv.
    It also proves that batching reduces planner steps without reducing tmux
    requests, and that Workspace's public default matches ``ws-batch``. A
    negative control confirms the equality gate is not vacuous.
    """
    scenarios = parse_scenarios(shapes)
    failures: list[str] = []
    shape_reports: list[str] = []
    for scenario in scenarios:
        wins, panes = scenario.windows, scenario.panes
        oracle, rows = check_parity(wins, panes)
        # Negative control: a non-empty oracle whose prefix differs from itself
        # proves the `== oracle` check below can actually catch a dropped op.
        if not oracle or oracle[:-1] == oracle:
            failures.append(f"{wins}x{panes}: negative control vacuous (empty oracle)")
        failures.extend(
            f"{wins}x{panes}: {label} diverges from the mock oracle"
            for label, agrees in rows
            if not agrees
        )
        layer_shapes = {
            name: execution_shape(layer, wins, panes) for name, layer in LAYERS.items()
        }
        plan_seq_steps = layer_shapes["plan-seq"].planner_steps
        plan_batch_steps = layer_shapes["plan-batch"].planner_steps
        ws_seq_steps = layer_shapes["ws-seq"].planner_steps
        ws_batch_steps = layer_shapes["ws-batch"].planner_steps
        if plan_batch_steps is None or plan_seq_steps is None:
            failures.append(f"{wins}x{panes}: plan-batch did not report planner steps")
        elif plan_seq_steps <= plan_batch_steps:
            failures.append(f"{wins}x{panes}: plan batching did not reduce steps")
        if ws_batch_steps is None or ws_seq_steps is None:
            failures.append(f"{wins}x{panes}: ws-batch did not report planner steps")
        elif ws_seq_steps <= ws_batch_steps:
            failures.append(f"{wins}x{panes}: workspace batching did not reduce steps")
        if layer_shapes["default"] != layer_shapes["ws-batch"]:
            failures.append(f"{wins}x{panes}: workspace default is not ws-batch")
        if len({shape.tmux_requests for shape in layer_shapes.values()}) != 1:
            failures.append(f"{wins}x{panes}: layers emit different request counts")
        if (
            plan_seq_steps is None
            or plan_batch_steps is None
            or ws_seq_steps is None
            or ws_batch_steps is None
        ):
            continue
        scale = scenario.sessions
        shape_reports.append(
            f"{scenario.label}: {len(oracle) * scale} requests; "
            f"plan {plan_seq_steps * scale}->{plan_batch_steps * scale} steps; "
            f"workspace {ws_seq_steps * scale}->{ws_batch_steps * scale} steps"
        )
    if failures:
        for problem in failures:
            console.print(f"[red]FAIL[/red] {problem}")
        raise typer.Exit(1)
    console.print(
        f"[green]contract OK[/green] -- every layer x {{sync,async}} renders the "
        f"mock oracle's argv across {len(scenarios)} scenario(s); batching shape and "
        "negative controls passed"
    )
    for report in shape_reports:
        console.print(f"[dim]{report}[/dim]")


@app.command()
def concurrency(
    shape: str = typer.Option("1x4", help="WxP shape of each session"),
    transport: str = typer.Option("control_mode", help="subprocess | control_mode"),
    layer: str = typer.Option("default", help="expression layer"),
    k: int = typer.Option(4, help="independent sessions to build"),
    runs: int = typer.Option(5, help="timed repeats"),
    warmup: int = typer.Option(1, help="warmup repeats"),
) -> None:
    """Explore K independent sessions: sync serial vs async gather wall time.

    This probe has asymmetric engine-startup boundaries, fixed strategy order,
    and no async-sequential or event-loop-lag control. Its output is diagnostic,
    not evidence for async speed or health.
    """
    wins, panes = parse_shape(shape)
    tp = TRANSPORTS[transport]
    lay = LAYERS[layer]

    def timed_serial() -> float:
        server = new_server()
        try:
            return _serial_build(tp, lay, server, k, wins, panes)
        finally:
            with contextlib.suppress(Exception):
                server.kill()

    def timed_gather() -> float:
        server = new_server()
        try:
            return asyncio.run(_gather_build(tp, lay, server, k, wins, panes))
        finally:
            with contextlib.suppress(Exception):
                server.kill()

    for _ in range(warmup):
        timed_serial()
        timed_gather()
    serial = [timed_serial() for _ in range(runs)]
    gather = [timed_gather() for _ in range(runs)]

    serial_stat = summarize(serial)
    gather_stat = summarize(gather)
    table = rich.table.Table(
        title=f"[bold]K={k} x ({wins}x{panes}) sessions -- {transport} / {layer}"
        f"  -- wall ms[/bold]"
    )
    table.add_column("strategy", style="cyan")
    for label in STAT_LABELS:
        table.add_column(label, justify="right")
    table.add_column("serial / gather", justify="right")
    table.add_row(
        "sync-serial",
        f"{int(serial_stat['n'])}",
        *[f"{serial_stat[k]:.1f}" for k in STAT_LABELS[1:]],
        "1.0x",
    )
    speed = (
        f"{serial_stat['median'] / gather_stat['median']:.2f}x"
        if gather_stat["median"]
        else "-"
    )
    table.add_row(
        "async-gather",
        f"{int(gather_stat['n'])}",
        *[f"{gather_stat[k]:.1f}" for k in STAT_LABELS[1:]],
        speed,
    )
    wide_console.print(table)


if __name__ == "__main__":
    app()
