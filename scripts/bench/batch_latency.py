#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["libtmux"]
#
# [tool.uv.sources]
# libtmux = { path = "../..", editable = true }
# ///
"""Compare sequential calls, a pipelined batch and a command group.

Runs N no-answer commands (``set-option``) three ways per engine and reports
the median wall time over ``--repeats`` runs plus how many processes were
forked:

* ``sequential`` -- ``engine.run`` once per command.
* ``batch`` -- ``engine.run_batch``: a subprocess engine forks per command, a
  control engine pipelines the writes and reads the replies in one wave.
* ``group`` -- :func:`libtmux.engines.batch.run_group`: one tmux command list,
  so one fork for a subprocess engine and one line for a control engine.

Reproduce with a tmux of your choice, in a short private directory::

    TMUX_TMPDIR=/tmp/lt-bb uv run scripts/bench/batch_latency.py --commands 20

The control connection is opened before timing, so the numbers are steady
state; ``processes_spawned`` counts forks after that point.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import pathlib
import statistics
import sys
import time
import typing as t

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from engine_latency import count_spawns
from primitives import new_server

from libtmux.engines import CommandRequest, ControlModeEngine, SubprocessEngine
from libtmux.engines.batch import run_group

if t.TYPE_CHECKING:
    from collections.abc import Callable

    from libtmux.engines import TmuxEngine


def requests_for(count: int) -> list[CommandRequest]:
    """Return *count* independent ``set-option`` commands."""
    return [
        CommandRequest.from_args("set-option", "-g", f"@bench{i}", str(i))
        for i in range(count)
    ]


def timed(action: Callable[[], object], repeats: int) -> dict[str, t.Any]:
    """Run *action* *repeats* times; report median ms and forks per run."""
    samples: list[float] = []
    with count_spawns() as spawned:
        for _ in range(repeats):
            started = time.perf_counter()
            action()
            samples.append((time.perf_counter() - started) * 1e3)
    return {
        "median_ms": round(statistics.median(samples), 3),
        "processes_spawned": spawned[0] // repeats,
    }


def measure(engine: TmuxEngine, count: int, repeats: int) -> dict[str, t.Any]:
    """Time the three strategies on *engine*."""
    requests = requests_for(count)
    engine.run(requests[0])  # opens a lazy connection outside the timing
    return {
        "sequential": timed(lambda: [engine.run(r) for r in requests], repeats),
        "batch": timed(lambda: engine.run_batch(requests), repeats),
        "group": timed(lambda: run_group(engine, requests), repeats),
    }


def main() -> int:
    """Measure both engines and print JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commands", type=int, default=20)
    parser.add_argument("--repeats", type=int, default=30)
    args = parser.parse_args()
    if args.commands < 1 or args.repeats < 1:
        parser.error("--commands and --repeats must be at least 1")

    server = new_server()
    server.new_session("bench", window_name="w0")
    try:
        out: dict[str, t.Any] = {
            "tmux": SubprocessEngine.for_server(server).tmux_version(),
            "commands": args.commands,
            "subprocess": measure(
                SubprocessEngine.for_server(server),
                args.commands,
                args.repeats,
            ),
        }
        with ControlModeEngine.for_server(server) as control:
            out["control"] = measure(control, args.commands, args.repeats)
    finally:
        with contextlib.suppress(Exception):
            server.kill()
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
