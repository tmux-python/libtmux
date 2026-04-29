#!/usr/bin/env python
"""Realistic libtmux workload bench across all three engines.

Runs the same five-phase workload (build / heavy query / light query
/ mutate / teardown) under ``subprocess``, ``imsg``, and
``control_mode`` and prints a per-phase + total wall-time table.

The microbench at ``bench-engines-ab.py`` measures per-call overhead
in isolation. This script measures the *aggregate* cost users actually
pay: the same sequence of high-level libtmux calls (``new_session``,
``new_window``, ``split_window``, ``windows`` accessor, ``panes``
accessor, ``rename_window``, ``capture_pane``, ``kill``) run from
public API entry points so wrapper overhead is included in the result.

Configurable via env vars:

  BENCH_QUERY_ITERS  int (default: 100) — iterations of the
                     light-query phase
  BENCH_REPEATS      int (default: 1)   — repeat the entire workload
                     this many times per engine and report the median
  BENCH_ENGINES      comma-separated subset of "subprocess,imsg,
                     control_mode" (default: all). Useful for Tachyon
                     profiling: ``BENCH_ENGINES=control_mode`` makes
                     the profile single-engine.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import statistics
import sys
import time
import typing as t
import uuid

import libtmux
from libtmux import pytest_plugin
from libtmux.engines.control_mode import ControlModeEngine
from libtmux.server import Server

if t.TYPE_CHECKING:
    from collections.abc import Callable


PhaseTimings = dict[str, float]


def _phase_build(server: Server) -> PhaseTimings:
    """Create one session, three windows, and split each window into two panes."""
    session = server.new_session(session_name="bench")
    windows = [session.active_window]
    windows.extend(
        session.new_window(window_name=f"w{index + 1}") for index in range(2)
    )
    for window in windows:
        window.split()
    return {"sessions": 1, "windows": len(windows), "panes": len(windows) * 2}


def _phase_heavy_query(server: Server) -> None:
    """Walk the full session/window/pane tree; read core attrs as users do."""
    for session in server.sessions:
        _ = session.session_name, session.session_id
        for window in session.windows:
            _ = window.window_name, window.window_id
            for pane in window.panes:
                _ = pane.pane_id, pane.pane_index


def _phase_light_query(server: Server, iters: int) -> None:
    """Tight loop of ``display-message`` — the existing microbench shape."""
    for _ in range(iters):
        server.cmd("display-message", "-p", "ok")


def _phase_mutate(server: Server) -> None:
    """Rename every window via the public API."""
    session = server.sessions[0]
    for index, window in enumerate(session.windows):
        window.rename_window(f"renamed_{index}")


def _phase_teardown(server: Server) -> None:
    """Kill the server via the public API."""
    server.kill()


def _bench_one_engine(
    label: str,
    server_factory: Callable[[], Server],
    query_iters: int,
) -> PhaseTimings:
    """Run the full five-phase workload once and return per-phase wall in ms."""
    server = server_factory()
    timings: PhaseTimings = {}
    try:
        t0 = time.perf_counter()
        _phase_build(server)
        timings["build_ms"] = 1000 * (time.perf_counter() - t0)

        t0 = time.perf_counter()
        _phase_heavy_query(server)
        timings["heavy_query_ms"] = 1000 * (time.perf_counter() - t0)

        t0 = time.perf_counter()
        _phase_light_query(server, query_iters)
        timings["light_query_ms"] = 1000 * (time.perf_counter() - t0)

        t0 = time.perf_counter()
        _phase_mutate(server)
        timings["mutate_ms"] = 1000 * (time.perf_counter() - t0)

        t0 = time.perf_counter()
        _phase_teardown(server)
        timings["teardown_ms"] = 1000 * (time.perf_counter() - t0)
    finally:
        if isinstance(server.engine, ControlModeEngine):
            with contextlib.suppress(Exception):
                server.engine.close()

    timings["total_ms"] = sum(v for k, v in timings.items() if k.endswith("_ms"))
    del label
    return timings


def main() -> int:
    """Run the workload bench across all three engines and print the results."""
    query_iters = int(os.environ.get("BENCH_QUERY_ITERS", "100"))
    repeats = int(os.environ.get("BENCH_REPEATS", "1"))
    requested = {
        e.strip()
        for e in os.environ.get(
            "BENCH_ENGINES",
            "subprocess,imsg,control_mode",
        ).split(",")
        if e.strip()
    }

    all_factories: list[tuple[str, Callable[[], Server]]] = [
        (
            "subprocess",
            lambda: libtmux.Server(
                socket_name=f"libtmux_workload_subprocess_{uuid.uuid4().hex[:6]}",
                engine="subprocess",
            ),
        ),
        (
            "imsg",
            lambda: libtmux.Server(
                socket_name=f"libtmux_workload_imsg_{uuid.uuid4().hex[:6]}",
                engine="imsg",
            ),
        ),
        (
            "control_mode",
            lambda: libtmux.Server(
                socket_name=f"libtmux_workload_cm_{uuid.uuid4().hex[:6]}",
                engine="control_mode",
            ),
        ),
    ]
    factories = [(label, f) for label, f in all_factories if label in requested]
    if not factories:
        sys.stderr.write(
            f"BENCH_ENGINES={os.environ.get('BENCH_ENGINES')!r} matched none "
            f"of {[label for label, _ in all_factories]}\n",
        )
        return 2

    print(
        f"# Workload bench: {repeats} repeat(s), "
        f"light-query phase = {query_iters} iters of display-message",
    )
    headers = ("engine", "build", "heavy_q", "light_q", "mutate", "teardown", "TOTAL")
    print(f"# {'  '.join(f'{h:>11}' for h in headers)}")

    for label, factory in factories:
        runs: list[PhaseTimings] = []
        for _ in range(repeats):
            runs.append(_bench_one_engine(label, factory, query_iters))
            # Defensive: kill any leftover socket between repeats.
            for run in runs[-1:]:
                _ = run
        median: PhaseTimings = {
            key: statistics.median(run[key] for run in runs) for key in runs[0]
        }
        row = (
            label,
            f"{median['build_ms']:.1f}ms",
            f"{median['heavy_query_ms']:.1f}ms",
            f"{median['light_query_ms']:.1f}ms",
            f"{median['mutate_ms']:.1f}ms",
            f"{median['teardown_ms']:.1f}ms",
            f"{median['total_ms']:.1f}ms",
        )
        print(f"  {'  '.join(f'{cell:>11}' for cell in row)}")

    # Best-effort socket cleanup in case kill_server failed under any engine.
    tmux_dir = pathlib.Path(f"/tmp/tmux-{os.geteuid()}")
    if tmux_dir.is_dir():
        for engine_label in ("subprocess", "imsg", "cm"):
            for entry in tmux_dir.iterdir():
                if entry.name.startswith(f"libtmux_workload_{engine_label}_"):
                    pytest_plugin._reap_test_server(entry.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
