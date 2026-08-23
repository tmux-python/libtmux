#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Run the active orchestration benchmark comparison matrix safely.

This is a thin supervisor around ``bench_orchestration.py``. It measures
nothing itself; it exists so a multi-cell comparison can be started without
the hazards that make ad-hoc invocations unreliable:

- two scale runs never overlap, because concurrent load perturbs every timing;
- the ambient tmux server is never contacted;
- a tmux socket path never exceeds the 107-byte limit the kernel imposes;
- evidence lands somewhere durable rather than in a temporary directory that a
  host restart will erase;
- private scratch is removed on success, failure, and interruption alike.

Cells run one at a time, in order. Each cell writes its own artifact, so a
failed cell never invalidates the ones already recorded.

Examples
--------
>>> pane_count(parse_shape("80x20x1"))
1600
>>> [str(cell) for cell in default_cells()[:2]]
['subprocess/sync', 'subprocess/async']
"""

from __future__ import annotations

import argparse
import collections.abc as cabc
import contextlib
import dataclasses
import fcntl
import functools
import json
import math
import os
import pathlib
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import types
import typing as t

_BENCHMARK = pathlib.Path(__file__).with_name("bench_orchestration.py")
_LANES = ("subprocess", "control")
_MODES = ("sync", "async")
# A Unix socket path must fit in sockaddr_un.sun_path. Keeping scratch short
# leaves room for the run-scoped subdirectory the benchmark appends.
_SCRATCH_PREFIX = "ltm-"
_MEMORY_FLOOR_BYTES = 8 * 1024**3


@functools.lru_cache(maxsize=1)
def child_interpreter() -> str:
    """Return an interpreter that can actually run the benchmark.

    ``sys.executable`` is this supervisor's own environment. Under a PEP 723
    invocation that environment is ephemeral and has no libtmux, so a child
    spawned from it dies on import with no explanation. Verify before
    spawning, and say what to do about it.

    The answer cannot change within one process, so it is probed once.
    """
    probe = subprocess.run(
        (sys.executable, "-c", "import libtmux, rich"),
        capture_output=True,
        check=False,
    )
    if probe.returncode == 0:
        return sys.executable
    message = (
        f"the interpreter running this supervisor ({sys.executable}) cannot "
        "import libtmux, so every benchmark child would fail on import.\n"
        "This happens when the script is run as a PEP 723 script, whose "
        "environment is isolated from the project.\n"
        "Run it through the project environment instead:\n"
        f"  uv run python scripts/orchestration_matrix.py"
    )
    raise SystemExit(message)


@dataclasses.dataclass(frozen=True)
class Cell:
    """One lane and mode pairing in the comparison matrix.

    Attributes
    ----------
    lane : str
        Transport lane, either ``subprocess`` or ``control``.
    mode : str
        Dispatch mode, either ``sync`` or ``async``.

    Examples
    --------
    >>> str(Cell("control", "async"))
    'control/async'
    """

    lane: str
    mode: str

    def __str__(self) -> str:
        """Return the ``lane/mode`` label used in reports."""
        return f"{self.lane}/{self.mode}"

    @property
    def slug(self) -> str:
        """Return a filesystem-safe cell name.

        Examples
        --------
        >>> Cell("control", "async").slug
        'control-async'
        """
        return f"{self.lane}-{self.mode}"


def default_cells() -> tuple[Cell, ...]:
    """Return every lane and mode pairing in a stable order.

    Returns
    -------
    tuple[Cell, ...]
        The four execution lanes the benchmark compares.

    Examples
    --------
    >>> len(default_cells())
    4
    """
    return tuple(Cell(lane, mode) for lane in _LANES for mode in _MODES)


def parse_shape(text: str) -> tuple[int, int, int]:
    """Parse ``SxWxP`` into sessions, windows per session, and panes per window.

    Parameters
    ----------
    text : str
        Topology in ``SxWxP`` notation.

    Returns
    -------
    tuple[int, int, int]
        Sessions, windows per session, and panes per window.

    Raises
    ------
    ValueError
        If the value is not three positive integers separated by ``x``.

    Examples
    --------
    >>> parse_shape("80x20x1")
    (80, 20, 1)
    >>> parse_shape("bad")
    Traceback (most recent call last):
    ValueError: shape must be SxWxP with positive integers: 'bad'
    """
    parts = text.lower().split("x")
    if len(parts) != 3:
        message = f"shape must be SxWxP with positive integers: {text!r}"
        raise ValueError(message)
    try:
        values = tuple(int(part) for part in parts)
    except ValueError:
        message = f"shape must be SxWxP with positive integers: {text!r}"
        raise ValueError(message) from None
    if any(value <= 0 for value in values):
        message = f"shape must be SxWxP with positive integers: {text!r}"
        raise ValueError(message)
    return t.cast("tuple[int, int, int]", values)


def pane_count(shape: tuple[int, int, int]) -> int:
    """Return the live pane count a shape produces.

    Examples
    --------
    >>> pane_count((100, 20, 2))
    4000
    """
    sessions, windows, panes = shape
    return sessions * windows * panes


def available_memory_bytes() -> int:
    """Return ``MemAvailable`` from the kernel, or zero when unreadable.

    Examples
    --------
    >>> available_memory_bytes() >= 0
    True
    """
    try:
        text = pathlib.Path("/proc/meminfo").read_text(encoding="utf-8")
    except OSError:
        return 0
    for line in text.splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    return 0


def checkout_residue(checkout: pathlib.Path) -> tuple[str, ...]:
    """Return descriptions of live benchmark processes owned by *checkout*.

    Parameters
    ----------
    checkout : pathlib.Path
        Repository root whose runs are considered in scope.

    Returns
    -------
    tuple[str, ...]
        One entry per surviving process; empty when the checkout is clean.

    Examples
    --------
    >>> isinstance(checkout_residue(pathlib.Path("/nonexistent")), tuple)
    True
    """
    try:
        listing = subprocess.run(
            ("ps", "-eo", "pid=,args="),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ()
    needles = ("bench_orchestration.py", "orchestration_fuzzer.py")
    return tuple(
        line.strip()[:120]
        for line in listing.splitlines()
        if str(checkout) in line and any(needle in line for needle in needles)
    )


def preflight(checkout: pathlib.Path, shape: tuple[int, int, int]) -> tuple[str, ...]:
    """Return blocking reasons why a matrix must not start now.

    Parameters
    ----------
    checkout : pathlib.Path
        Repository root whose runs are considered in scope.
    shape : tuple[int, int, int]
        Requested topology, used only for the reported pane count.

    Returns
    -------
    tuple[str, ...]
        Blocking reasons; empty when it is safe to proceed.

    Examples
    --------
    >>> isinstance(preflight(pathlib.Path("/nonexistent"), (1, 1, 1)), tuple)
    True
    """
    blockers = []
    memory = available_memory_bytes()
    if memory and memory < _MEMORY_FLOOR_BYTES:
        blockers.append(
            f"available memory {memory / 1e9:.1f} GB is below the "
            f"{_MEMORY_FLOOR_BYTES / 1e9:.0f} GB floor"
        )
    residue = checkout_residue(checkout)
    if residue:
        blockers.append(f"{len(residue)} benchmark process(es) still running")
    if not _BENCHMARK.is_file():
        blockers.append(f"benchmark entry point is missing: {_BENCHMARK.name}")
    del shape
    return tuple(blockers)


@contextlib.contextmanager
def exclusive_lock(path: pathlib.Path) -> t.Iterator[None]:
    """Hold an advisory lock so two matrices cannot overlap.

    Parameters
    ----------
    path : pathlib.Path
        Lock file path; created when absent.

    Yields
    ------
    None
        While the lock is held.

    Raises
    ------
    SystemExit
        If another matrix already holds the lock.

    Examples
    --------
    >>> with tempfile.TemporaryDirectory() as temporary:
    ...     lock = pathlib.Path(temporary) / "lock"
    ...     with exclusive_lock(lock):
    ...         lock.exists()
    True
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            message = f"another orchestration matrix already holds {path}"
            raise SystemExit(message) from None
        handle.write(f"{os.getpid()}\n")
        handle.flush()
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def summarize(artifact: pathlib.Path) -> dict[str, object]:
    """Return the comparison facts a finished cell contributes.

    Parameters
    ----------
    artifact : pathlib.Path
        JSON report written by one cell.

    Returns
    -------
    dict[str, object]
        Status, completed phase count, and per-phase median nanoseconds.

    Examples
    --------
    >>> with tempfile.TemporaryDirectory() as temporary:
    ...     path = pathlib.Path(temporary) / "r.json"
    ...     _ = path.write_text('{"status": "completed", "phases": []}')
    ...     summarize(path)["status"]
    'completed'
    """
    try:
        report = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return {"status": f"unreadable: {type(error).__name__}", "phases": {}}
    phases = report.get("phases") or []
    medians: dict[str, float] = {}
    for phase in phases:
        samples = [
            sample["duration_ns"]
            for sample in (phase.get("samples") or [])
            if sample.get("accepted") and sample.get("verified")
        ]
        if samples:
            medians[phase["name"]] = sorted(samples)[len(samples) // 2]
    return {
        "status": report.get("status"),
        "failed_phase": report.get("failed_phase"),
        "completed": sum(1 for p in phases if p.get("status") == "completed"),
        "total": len(phases),
        "phases": medians,
    }


def reportable_percentiles(samples: int) -> tuple[int, ...]:
    """Return the percentiles *samples* observations can actually resolve.

    A percentile at quantile ``q`` needs at least ``1 / (1 - q)`` observations
    before it is distinguishable from the maximum. Below that it is the
    maximum wearing a different label, which is how a two-sample cell ends up
    printing a p99.

    Parameters
    ----------
    samples : int
        Accepted and verified timed samples in one cell.

    Returns
    -------
    tuple[int, ...]
        Percentiles worth rendering, ascending.

    Examples
    --------
    >>> reportable_percentiles(2)
    ()
    >>> reportable_percentiles(10)
    (90,)
    >>> reportable_percentiles(100)
    (90, 95, 99)
    """
    return tuple(
        percentile
        for percentile in (90, 95, 99)
        if samples >= round(100 / (100 - percentile))
    )


def _quantile(ordered: list[float], percentile: int) -> float:
    """Return the nearest-rank *percentile* of an ascending sequence.

    Examples
    --------
    >>> _quantile([1.0, 2.0, 3.0, 4.0], 50)
    2.0
    """
    rank = max(1, min(len(ordered), math.ceil(percentile / 100 * len(ordered))))
    return ordered[rank - 1]


def median_interval(
    samples: cabc.Sequence[float],
    *,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Return a distribution-free confidence interval for the median.

    Uses the order-statistic (sign-test) interval, which assumes nothing about
    the shape of the distribution. That matters here: phase timings are heavy
    tailed, so an interval derived from a standard deviation would understate
    the spread badly.

    Parameters
    ----------
    samples : Sequence[float]
        Accepted observations for one phase.
    confidence : float
        Two-sided coverage, 0.95 by default.

    Returns
    -------
    tuple[float, float]
        Lower and upper bound. Fewer than six observations cannot bound a
        median at all, so the interval is unbounded and every comparison
        against it is reported as unresolved rather than guessed.

    Examples
    --------
    >>> median_interval([5.0] * 10)
    (5.0, 5.0)
    >>> low, high = median_interval([1.0, 2.0, 3.0, 40.0, 50.0, 60.0])
    >>> low < high
    True
    >>> median_interval([1.0, 2.0])
    (0.0, inf)
    """
    ordered = sorted(samples)
    count = len(ordered)
    if count == 0:
        return (0.0, 0.0)
    if count < 6:
        return (0.0, math.inf)
    # Nearest-rank bounds from the binomial quantiles of the sign test.
    spread = statistics.NormalDist().inv_cdf(1 - (1 - confidence) / 2)
    half = spread * math.sqrt(count) / 2
    lower = max(0, math.floor(count / 2 - half))
    upper = min(count - 1, math.ceil(count / 2 + half) - 1)
    return (ordered[lower], ordered[upper])


def load_cells(root: pathlib.Path) -> dict[str, dict[str, object]]:
    """Return every cell artifact found under *root*, keyed by ``lane/mode``.

    Parameters
    ----------
    root : pathlib.Path
        Evidence directory holding one subdirectory per cell.

    Returns
    -------
    dict[str, dict[str, object]]
        Cell label mapped to its status and per-phase sample lists.

    Examples
    --------
    >>> load_cells(pathlib.Path("/nonexistent"))
    {}
    """
    cells: dict[str, dict[str, object]] = {}
    if not root.is_dir():
        return cells
    for artifact in sorted(root.glob("*/report.json")):
        try:
            report = json.loads(artifact.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        label = f"{report.get('lane')}/{report.get('mode')}"
        phases: dict[str, list[float]] = {}
        for phase in report.get("phases") or []:
            accepted = [
                sample["duration_ns"] / 1e6
                for sample in (phase.get("samples") or [])
                if sample.get("accepted") and sample.get("verified")
            ]
            if accepted:
                phases[phase["name"]] = sorted(accepted)
        cells[label] = {
            "status": report.get("status"),
            "failed_phase": report.get("failed_phase"),
            "phases": phases,
        }
    return cells


def render_matrix(root: pathlib.Path, *, baseline: str | None = None) -> str:
    """Render a cross-lane comparison from the cell artifacts under *root*.

    The rendered unit is the individual phase. A whole-iteration ratio is not
    reported, because summing phases makes the result a proxy for whichever
    phase is most expensive -- capture dominates every lane here -- rather than
    a statement about the lanes.

    Parameters
    ----------
    root : pathlib.Path
        Evidence directory holding one subdirectory per cell.
    baseline : str or None
        Cell label ratios are taken against; the slowest completed cell by
        default, so ratios read as "this many times faster than *baseline*".

    Returns
    -------
    str
        Markdown document; a short notice when no artifact was found.

    Examples
    --------
    >>> render_matrix(pathlib.Path("/nonexistent")).splitlines()[0]
    '# Orchestration matrix'
    """
    cells = load_cells(root)
    lines = ["# Orchestration matrix", ""]
    if not cells:
        lines += ["No cell artifacts were found.", ""]
        return "\n".join(lines)

    counts = {
        label: max(
            (len(v) for v in t.cast("dict[str, t.Any]", cell["phases"]).values()),
            default=0,
        )
        for label, cell in cells.items()
    }
    smallest = min(counts.values()) if counts else 0
    percentiles = reportable_percentiles(smallest)

    lines += [
        "> Local descriptive evidence only; not causal or machine-independent.",
        "",
        f"Cells hold at least {smallest} timed samples, so this report shows "
        + (
            "median and " + ", ".join(f"p{p}" for p in percentiles)
            if percentiles
            else "the median only"
        )
        + ".",
        "",
        "## Cells",
        "",
        "| Cell | Status | Timed samples |",
        "| --- | --- | ---: |",
    ]
    for label, cell in sorted(cells.items()):
        status = t.cast("str", cell["status"]) or "unknown"
        failed = cell.get("failed_phase")
        note = f"{status}" + (f" ({failed})" if failed else "")
        lines.append(f"| `{label}` | {note} | {counts[label]} |")

    completed = {
        label: cell for label, cell in cells.items() if cell["status"] == "completed"
    }
    if len(completed) < 2:
        lines += [
            "",
            "Fewer than two cells completed, so no lane comparison is offered.",
            "",
        ]
        return "\n".join(lines)

    phase_names = sorted(
        {
            name
            for cell in completed.values()
            for name in t.cast("dict[str, t.Any]", cell["phases"])
        }
    )
    del baseline

    labels = sorted(completed)
    header = "| Phase | " + " | ".join(f"`{label}`" for label in labels)
    header += " | Fastest | Spread |"
    lines += [
        "",
        "## Per-phase medians",
        "",
        (
            "Each row is one phase. Spread is the slowest completed cell "
            "divided by the fastest, for that phase alone."
        ),
        "",
        header,
        "| --- | " + " | ".join("---:" for _ in labels) + " | --- | ---: |",
    ]
    for name in phase_names:
        cells_row = []
        medians: dict[str, float] = {}
        for label in labels:
            values = t.cast("dict[str, t.Any]", completed[label]["phases"]).get(name)
            if not values:
                cells_row.append("n/a")
                continue
            median = _quantile(values, 50)
            medians[label] = median
            cells_row.append(f"{median:.1f} ms")
        fastest, spread = "n/a", "n/a"
        if medians:
            winner = min(medians, key=lambda label: medians[label])
            loser = max(medians, key=lambda label: medians[label])
            fastest = f"`{winner}`"
            best = medians[winner]
            if best > 0 and len(medians) > 1:
                # Only claim a ratio the run-to-run spread can actually
                # separate. Overlapping intervals mean the difference is
                # inside this benchmark's noise, not a finding.
                _, best_high = median_interval(
                    t.cast("dict[str, t.Any]", completed[winner]["phases"])[name]
                )
                worst_low, _ = median_interval(
                    t.cast("dict[str, t.Any]", completed[loser]["phases"])[name]
                )
                if worst_low > best_high:
                    spread = f"{medians[loser] / best:.1f}x"
                else:
                    fastest = "unresolved"
                    spread = "unresolved"
        lines.append(
            f"| `{name}` | " + " | ".join(cells_row) + f" | {fastest} | {spread} |"
        )

    for percentile in percentiles:
        lines += [
            "",
            f"## Per-phase p{percentile}",
            "",
            "| Phase | " + " | ".join(f"`{label}`" for label in labels) + " |",
            "| --- | " + " | ".join("---:" for _ in labels) + " |",
        ]
        for name in phase_names:
            row = []
            for label in labels:
                values = t.cast("dict[str, t.Any]", completed[label]["phases"]).get(
                    name
                )
                row.append(
                    f"{_quantile(values, percentile):.1f} ms" if values else "n/a"
                )
            lines.append(f"| `{name}` | " + " | ".join(row) + " |")

    lines += [
        "",
        "## What these ratios may claim",
        "",
        (
            "A per-phase ratio is a statement about that phase's request "
            "pattern on that transport, on this host, at this topology. It is "
            "not a general engine speedup, and it does not transfer to a "
            "workload with a different mix of phases."
        ),
        "",
    ]
    return "\n".join(lines)


def run_cell(
    cell: Cell,
    *,
    shape: str,
    runs: int,
    warmup: int,
    seed: int,
    evidence_root: pathlib.Path,
    timeout_s: float,
    orm: bool = False,
) -> dict[str, object]:
    """Run one cell to completion and return its summary.

    Scratch is created short and removed on every exit path, including an
    interrupt, so a cancelled matrix leaves no socket or private directory.

    Parameters
    ----------
    cell : Cell
        Lane and mode to execute.
    shape : str
        Topology in ``SxWxP`` notation.
    runs : int
        Timed invocations retained per repeatable phase.
    warmup : int
        Untimed invocations before each repeatable phase.
    seed : int
        Schedule seed shared by every cell.
    evidence_root : pathlib.Path
        Durable directory receiving each cell's artifact.
    timeout_s : float
        Hard limit for one cell.

    Returns
    -------
    dict[str, object]
        Summary of the cell, including wall seconds and exit status.

    Examples
    --------
    >>> callable(run_cell)
    True
    """
    out = evidence_root / cell.slug
    out.mkdir(parents=True, exist_ok=True)
    scratch = pathlib.Path(tempfile.mkdtemp(prefix=_SCRATCH_PREFIX, dir="/tmp"))
    environment = dict(os.environ)
    for name in ("TMUX", "TMUX_PANE", "VIRTUAL_ENV"):
        environment.pop(name, None)
    command = (
        child_interpreter(),
        str(_BENCHMARK),
        "run",
        "--shape",
        shape,
        "--lane",
        cell.lane,
        "--mode",
        cell.mode,
        "--runs",
        str(runs),
        "--warmup",
        str(warmup),
        "--seed",
        str(seed),
        "--output",
        str(out / "report.json"),
        "--markdown-output",
        str(out / "report.md"),
        "--scratch-root",
        str(scratch),
        *(("--with-orm",) if orm else ()),
    )
    started = time.monotonic()
    returncode: int | None = None
    try:
        with (out / "run.log").open("wb") as log:
            process = subprocess.Popen(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                env=environment,
                cwd=str(_BENCHMARK.parent.parent),
            )
            try:
                returncode = process.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                process.send_signal(signal.SIGINT)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    returncode = process.wait(timeout=120)
                if returncode is None:
                    process.kill()
                    returncode = process.wait(timeout=60)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    elapsed = time.monotonic() - started
    summary = summarize(out / "report.json")
    summary["cell"] = str(cell)
    summary["returncode"] = returncode
    summary["wall_s"] = round(elapsed, 1)
    return summary


def _install_cleanup(scratch_prefix: str) -> None:
    """Remove this run's leftover scratch on SIGINT and SIGTERM."""

    def handler(signum: int, frame: types.FrameType | None) -> None:
        del frame
        for path in pathlib.Path("/tmp").glob(f"{scratch_prefix}*"):
            shutil.rmtree(path, ignore_errors=True)
        raise SystemExit(128 + signum)

    for signum in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(ValueError, OSError):
            signal.signal(signum, handler)


def build_parser() -> argparse.ArgumentParser:
    """Return the command-line parser.

    Examples
    --------
    >>> build_parser().prog
    'orchestration_matrix.py'
    """
    parser = argparse.ArgumentParser(
        prog="orchestration_matrix.py",
        description=(
            "Run the orchestration benchmark across execution lanes, one cell "
            "at a time, with preflight checks, an exclusive lock, durable "
            "evidence, and guaranteed scratch cleanup."
        ),
        epilog=(
            "Cells never run concurrently: overlapping scale runs perturb every "
            "timing they produce."
        ),
    )
    # Defaults are the combination measured end to end at just under 24
    # minutes for four cells. Subprocess per-iteration cost grows
    # superlinearly with panes -- about 9 seconds at 800 against roughly 49 at
    # 1,600 -- so raising either value pushes a plain invocation past an hour.
    parser.add_argument("--shape", default="40x20x1", help="topology in SxWxP notation")
    parser.add_argument(
        "--runs", type=int, default=20, help="timed invocations per repeatable phase"
    )
    parser.add_argument(
        "--warmup", type=int, default=2, help="untimed invocations before each phase"
    )
    parser.add_argument("--seed", type=int, default=20260819, help="schedule seed")
    parser.add_argument(
        "--cells",
        default="all",
        help="comma-separated lane/mode cells, or 'all' for every lane",
    )
    parser.add_argument(
        "--evidence-root",
        type=pathlib.Path,
        default=pathlib.Path.home() / ".local/share/libtmux-orchestration-matrix",
        help="durable directory receiving one artifact per cell",
    )
    parser.add_argument(
        "--cell-timeout-seconds",
        type=float,
        default=1800.0,
        help="hard limit for a single cell",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="continue past non-fatal preflight blockers",
    )
    parser.add_argument(
        "--with-orm",
        action="store_true",
        help="also measure the classic ORM enumeration reference in every cell",
    )
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="re-render an existing evidence root without running any cell",
    )
    return parser


def _selected_cells(spec: str) -> tuple[Cell, ...]:
    """Return the cells named by *spec*.

    Examples
    --------
    >>> [str(c) for c in _selected_cells("control/async")]
    ['control/async']
    """
    if spec.strip().lower() == "all":
        return default_cells()
    cells = []
    for item in spec.split(","):
        lane, _, mode = item.strip().partition("/")
        if lane not in _LANES or mode not in _MODES:
            message = f"unknown cell {item.strip()!r}; expected lane/mode"
            raise SystemExit(message)
        cells.append(Cell(lane, mode))
    return tuple(cells)


def main(argv: t.Sequence[str] | None = None) -> int:
    """Run the requested matrix and report one line per cell.

    Examples
    --------
    >>> main(["--help"])
    Traceback (most recent call last):
    SystemExit: 0
    """
    arguments = build_parser().parse_args(argv)
    shape = parse_shape(arguments.shape)
    cells = _selected_cells(arguments.cells)
    checkout = _BENCHMARK.parent.parent

    if arguments.render_only:
        report = arguments.evidence_root / "matrix.md"
        report.write_text(render_matrix(arguments.evidence_root), encoding="utf-8")
        print(f"rendered {report}")
        return 0

    blockers = preflight(checkout, shape)
    if blockers:
        for blocker in blockers:
            print(f"preflight: {blocker}", file=sys.stderr)
        if not arguments.force:
            return 2

    _install_cleanup(_SCRATCH_PREFIX)
    arguments.evidence_root.mkdir(parents=True, exist_ok=True)
    print(
        f"shape {arguments.shape} ({pane_count(shape)} panes), "
        f"runs {arguments.runs}, warmup {arguments.warmup}, "
        f"{len(cells)} cell(s), sequential"
    )

    summaries = []
    with exclusive_lock(arguments.evidence_root / ".lock"):
        for cell in cells:
            summary = run_cell(
                cell,
                shape=arguments.shape,
                runs=arguments.runs,
                warmup=arguments.warmup,
                seed=arguments.seed,
                evidence_root=arguments.evidence_root,
                timeout_s=arguments.cell_timeout_seconds,
                orm=arguments.with_orm,
            )
            summaries.append(summary)
            print(
                f"  {summary['cell']:<19} rc={summary['returncode']:<3} "
                f"{summary['wall_s']:>7.1f}s  {summary['status']}  "
                f"{summary['completed']}/{summary['total']} phases"
                + (
                    f"  failed={summary['failed_phase']}"
                    if summary.get("failed_phase")
                    else ""
                )
            )

    (arguments.evidence_root / "matrix.json").write_text(
        json.dumps(summaries, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = arguments.evidence_root / "matrix.md"
    report.write_text(render_matrix(arguments.evidence_root), encoding="utf-8")
    print(f"cross-lane report: {report}")
    residue = checkout_residue(checkout)
    if residue:
        print(f"WARNING: {len(residue)} benchmark process(es) remain", file=sys.stderr)
        return 1
    completed = sum(1 for s in summaries if s["status"] == "completed")
    print(f"{completed}/{len(summaries)} cells completed; no residue")
    return 0 if completed == len(summaries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
