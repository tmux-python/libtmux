#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Find where the active orchestration workload buckles, and on which axis.

This is a pressure test, not a comparison. It answers a different question
from ``matrix.py``: not "which lane is faster" but "how far can
this host be pushed before a phase stops completing, and which dimension is
responsible".

Each rung runs a single timed invocation with no warmup, because only the
outcome matters. Ladders vary one dimension at a time so a failure is
attributable:

- ``panes`` holds sessions and windows fixed and raises panes per window;
- ``windows`` holds sessions and panes fixed and raises windows per session;
- ``sessions`` holds windows and panes fixed and raises sessions.

A rung that fails records the phase that failed, which is the useful part: at
this scale different dimensions surrender in different phases.

Examples
--------
>>> [str(shape) for shape in ladder("panes")[:3]]
['80x20x1', '80x20x2', '80x20x3']
>>> ladder("sessions")[0].panes
1600
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import fcntl
import functools
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import types
import typing as t

_BENCHMARK = pathlib.Path(__file__).with_name("benchmark.py")
_SCRATCH_PREFIX = "lts-"
_MEMORY_FLOOR_BYTES = 8 * 1024**3
# The benchmark's own progress watchdog is a flat 120s, which does not scale
# with the topology a rung builds. Measured on this ladder's own shapes, one
# control/async pass costs 14.3s at 400 panes, 24.0s at 800, 52.5s at 1200 and
# 177.5s at 1600 -- superlinear, so a fixed allowance turns into a false
# failure exactly where the harness is meant to be measuring. These give a
# per-rung allowance instead, still bounded by --rung-timeout-seconds.
_WATCHDOG_BASE_S = 120.0
_WATCHDOG_PER_PANE_S = 0.25


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
        f"  uv run python scripts/orchestration/stress.py"
    )
    raise SystemExit(message)


@dataclasses.dataclass(frozen=True)
class Shape:
    """One topology on a stress ladder.

    Attributes
    ----------
    sessions : int
        Session count.
    windows : int
        Windows per session.
    panes : int
        Panes per window.

    Examples
    --------
    >>> str(Shape(80, 20, 2))
    '80x20x2'
    >>> Shape(80, 20, 2).panes
    3200
    """

    sessions: int
    windows: int
    panes_per_window: int

    def __str__(self) -> str:
        """Return ``SxWxP`` notation."""
        return f"{self.sessions}x{self.windows}x{self.panes_per_window}"

    def __format__(self, spec: str) -> str:
        """Format the ``SxWxP`` notation, so column alignment works.

        A dataclass inherits ``object.__format__``, which rejects any
        non-empty spec, and the reporting loop aligns shapes into columns.

        Examples
        --------
        >>> f"{Shape(80, 20, 2):<10}|"
        '80x20x2   |'
        """
        return format(str(self), spec)

    @property
    def panes(self) -> int:
        """Return the live pane count this shape creates."""
        return self.sessions * self.windows * self.panes_per_window


def ladder(axis: str) -> tuple[Shape, ...]:
    """Return the escalating shapes for one axis.

    Every ladder starts from the same base, so rungs are comparable across
    axes at equal pane counts.

    Parameters
    ----------
    axis : {"panes", "windows", "sessions"}
        Dimension to escalate.

    Returns
    -------
    tuple[Shape, ...]
        Shapes in ascending pressure order.

    Raises
    ------
    ValueError
        If *axis* is not a known dimension.

    Examples
    --------
    >>> ladder("windows")[1].windows
    30
    >>> ladder("nope")
    Traceback (most recent call last):
    ValueError: unknown stress axis: 'nope'
    """
    if axis == "panes":
        return tuple(Shape(80, 20, step) for step in (1, 2, 3, 4))
    if axis == "windows":
        return tuple(Shape(80, step, 1) for step in (20, 30, 40, 60, 80))
    if axis == "sessions":
        return tuple(Shape(step, 20, 1) for step in (80, 100, 140, 200))
    message = f"unknown stress axis: {axis!r}"
    raise ValueError(message)


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


@contextlib.contextmanager
def exclusive_lock(path: pathlib.Path) -> t.Iterator[None]:
    """Hold an advisory lock so no other scale run overlaps this one.

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
            message = f"another scale run already holds {path}"
            raise SystemExit(message) from None
        handle.write(f"{os.getpid()}\n")
        handle.flush()
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def rung_outcome(artifact: pathlib.Path, returncode: int | None) -> dict[str, object]:
    """Summarize one rung from its artifact.

    Parameters
    ----------
    artifact : pathlib.Path
        JSON report the rung produced, which may be absent.
    returncode : int or None
        Exit status of the rung.

    Returns
    -------
    dict[str, object]
        Status, the phase that failed, and how many phases completed.

    Examples
    --------
    >>> rung_outcome(pathlib.Path("/nonexistent"), 2)["status"]
    'no artifact'
    """
    try:
        report = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "no artifact", "failed_phase": None, "completed": 0}
    phases = report.get("phases") or []
    return {
        "status": report.get("status"),
        "failed_phase": report.get("failed_phase"),
        "completed": sum(1 for p in phases if p.get("status") == "completed"),
        "total": len(phases),
        "returncode": returncode,
    }


def watchdog_seconds(shape: Shape, rung_timeout_s: float) -> float:
    """Return the progress-gap allowance for *shape*, capped by the rung limit.

    The allowance has to grow with the topology: the same phase that finishes
    well inside 120 seconds at 400 panes needs several times that at 1600, so a
    flat watchdog reports a slow rung as a stuck one and stops the ladder short
    of anything real. The cap keeps a genuinely stuck rung from outliving the
    hard per-rung limit that would have killed it anyway.

    Parameters
    ----------
    shape : Shape
        Topology this rung builds.
    rung_timeout_s : float
        Hard limit for the whole rung, which the allowance never exceeds.

    Returns
    -------
    float
        Seconds a rung may make no progress before it is declared stuck.

    Examples
    --------
    >>> watchdog_seconds(Shape(80, 20, 1), 900.0)
    520.0
    >>> watchdog_seconds(Shape(20, 20, 1), 900.0)
    220.0

    A large topology is bounded by the rung limit rather than the formula:

    >>> watchdog_seconds(Shape(80, 20, 4), 900.0)
    900.0
    """
    scaled = _WATCHDOG_BASE_S + shape.panes * _WATCHDOG_PER_PANE_S
    return min(scaled, rung_timeout_s)


def run_rung(
    shape: Shape,
    *,
    lane: str,
    mode: str,
    evidence_root: pathlib.Path,
    timeout_s: float,
) -> dict[str, object]:
    """Run one rung and return its outcome.

    Scratch is removed on every exit path, so an aborted ladder leaves no
    socket or private directory behind.

    Examples
    --------
    >>> callable(run_rung)
    True
    """
    out = evidence_root / f"{shape}-{lane}-{mode}"
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
        str(shape),
        "--lane",
        lane,
        "--mode",
        mode,
        "--runs",
        "1",
        "--warmup",
        "0",
        "--seed",
        "20260819",
        "--output",
        str(out / "report.json"),
        "--scratch-root",
        str(scratch),
        "--watchdog-seconds",
        str(watchdog_seconds(shape, timeout_s)),
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
    outcome = rung_outcome(out / "report.json", returncode)
    outcome["shape"] = str(shape)
    outcome["panes"] = shape.panes
    outcome["wall_s"] = round(time.monotonic() - started, 1)
    return outcome


def _install_cleanup(prefix: str) -> None:
    """Remove this run's leftover scratch on SIGINT and SIGTERM."""

    def handler(signum: int, frame: types.FrameType | None) -> None:
        del frame
        for path in pathlib.Path("/tmp").glob(f"{prefix}*"):
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
    'scripts/orchestration/stress.py'
    """
    parser = argparse.ArgumentParser(
        prog="scripts/orchestration/stress.py",
        description=(
            "Escalate one topology dimension at a time until a phase stops "
            "completing, recording which phase surrendered and at what pane "
            "count."
        ),
        epilog=(
            "Each rung uses a single timed invocation and no warmup, because "
            "only the outcome matters. This is a pressure test; use "
            "matrix.py to compare lanes."
        ),
    )
    parser.add_argument(
        "--axis",
        default="panes",
        help="panes, windows, sessions, or all",
    )
    parser.add_argument("--lane", default="control", choices=("subprocess", "control"))
    parser.add_argument("--mode", default="async", choices=("sync", "async"))
    parser.add_argument(
        "--evidence-root",
        type=pathlib.Path,
        default=pathlib.Path.home() / ".local/share/libtmux-orchestration-stress",
        help="durable directory receiving one artifact per rung",
    )
    parser.add_argument(
        "--budget-seconds",
        type=float,
        default=3600.0,
        help="stop starting new rungs once this much wall time has elapsed",
    )
    parser.add_argument(
        "--rung-timeout-seconds",
        type=float,
        default=900.0,
        help="hard limit for one rung",
    )
    parser.add_argument(
        "--stop-after-failures",
        type=int,
        default=1,
        help="stop an axis after this many failed rungs",
    )
    return parser


def main(argv: t.Sequence[str] | None = None) -> int:
    """Walk the requested ladders and report where each axis buckles.

    Examples
    --------
    >>> main(["--help"])
    Traceback (most recent call last):
    SystemExit: 0
    """
    arguments = build_parser().parse_args(argv)
    axes = (
        ("panes", "windows", "sessions")
        if arguments.axis == "all"
        else (arguments.axis,)
    )
    for axis in axes:
        ladder(axis)  # validate before starting any work

    memory = available_memory_bytes()
    if memory and memory < _MEMORY_FLOOR_BYTES:
        print(
            f"preflight: available memory {memory / 1e9:.1f} GB is below the floor",
            file=sys.stderr,
        )
        return 2

    _install_cleanup(_SCRATCH_PREFIX)
    arguments.evidence_root.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    results: list[dict[str, object]] = []

    with exclusive_lock(arguments.evidence_root / ".lock"):
        for axis in axes:
            failures = 0
            print(f"\naxis: {axis} ({arguments.lane}/{arguments.mode})")
            for shape in ladder(axis):
                elapsed = time.monotonic() - started
                if elapsed > arguments.budget_seconds:
                    print(
                        f"  budget of {arguments.budget_seconds:.0f}s reached; "
                        f"{shape} and beyond not attempted"
                    )
                    break
                outcome = run_rung(
                    shape,
                    lane=arguments.lane,
                    mode=arguments.mode,
                    evidence_root=arguments.evidence_root,
                    timeout_s=arguments.rung_timeout_seconds,
                )
                outcome["axis"] = axis
                results.append(outcome)
                note = (
                    f"  failed at {outcome['failed_phase']}"
                    if outcome["status"] != "completed"
                    else ""
                )
                print(
                    f"  {shape:<10} {outcome['panes']:>6} panes  "
                    f"{outcome['wall_s']:>7.1f}s  {outcome['status']}"
                    f"  {outcome['completed']}/{outcome.get('total', '?')} phases"
                    f"{note}"
                )
                if outcome["status"] != "completed":
                    failures += 1
                    if failures >= arguments.stop_after_failures:
                        print(f"  stopping {axis}: {failures} failed rung(s)")
                        break

    (arguments.evidence_root / "stress.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (arguments.evidence_root / "stress.md").write_text(
        render_stress(results), encoding="utf-8"
    )
    print(f"\nreport: {arguments.evidence_root / 'stress.md'}")
    return 0


def render_stress(results: list[dict[str, object]]) -> str:
    """Render the ladder outcomes as Markdown.

    Examples
    --------
    >>> render_stress([]).splitlines()[0]
    '# Orchestration stress'
    """
    lines = [
        "# Orchestration stress",
        "",
        "> Where each topology dimension stops completing, on this host.",
        "",
    ]
    if not results:
        lines += ["No rungs were attempted.", ""]
        return "\n".join(lines)
    lines += [
        "| Axis | Shape | Panes | Wall | Outcome | Phases | Surrendered at |",
        "| --- | --- | ---: | ---: | --- | ---: | --- |",
    ]
    for row in results:
        failed = row.get("failed_phase") or "-"
        lines.append(
            f"| {row.get('axis')} | `{row.get('shape')}` | {row.get('panes')} "
            f"| {row.get('wall_s')}s | {row.get('status')} "
            f"| {row.get('completed')}/{row.get('total', '?')} | `{failed}` |"
        )
    lines += [
        "",
        (
            "A rung is one timed invocation with no warmup: only the outcome "
            "is meaningful, never the timing."
        ),
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
