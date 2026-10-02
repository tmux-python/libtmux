#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["libtmux"]
#
# [tool.uv.sources]
# libtmux = { path = "../..", editable = true }
# ///
"""Compare per-command latency and process spawns across engines.

Runs the same requests through :class:`~libtmux.engines.SubprocessEngine` (one
fork per command) and :class:`~libtmux.engines.ControlModeEngine` (one
persistent client) against a private tmux server, and reports latency
percentiles in milliseconds plus how many processes each engine spawned.

Reproduce with a tmux of your choice, in a short private directory::

    TMUX_TMPDIR=/tmp/lt-en uv run scripts/bench/engine_latency.py --calls 300

The first control-mode call includes opening the connection and is reported
separately as ``connect_ms``, so the percentiles describe steady state.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import pathlib
import subprocess
import sys
import time
import typing as t

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from primitives import new_server, summarize

from libtmux.engines import CommandRequest, ControlModeEngine, SubprocessEngine

if t.TYPE_CHECKING:
    from libtmux.engines import TmuxEngine

REQUESTS = {
    "display-message": CommandRequest.from_args("display-message", "-p", "#{pane_id}"),
    "list-panes -a": CommandRequest.from_args("list-panes", "-a"),
}


@contextlib.contextmanager
def count_spawns() -> t.Iterator[list[int]]:
    """Count every :class:`subprocess.Popen` created inside the block."""
    counter = [0]
    original = subprocess.Popen

    class Counting(original):  # type: ignore[misc, valid-type]
        def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
            counter[0] += 1
            super().__init__(*args, **kwargs)

    subprocess.Popen = Counting  # type: ignore[misc]
    try:
        yield counter
    finally:
        subprocess.Popen = original  # type: ignore[misc]


def measure(engine: TmuxEngine, calls: int) -> dict[str, t.Any]:
    """Time *calls* of each request through *engine*; count spawned processes."""
    result: dict[str, t.Any] = {}
    with count_spawns() as spawned:
        started = time.perf_counter()
        engine.run(REQUESTS["display-message"])  # opens the connection if lazy
        result["first_call_ms"] = round((time.perf_counter() - started) * 1e3, 3)
        for name, request in REQUESTS.items():
            samples: list[float] = []
            for _ in range(calls):
                started = time.perf_counter()
                engine.run(request)
                samples.append((time.perf_counter() - started) * 1e3)
            summary = summarize(samples)
            result[name] = {
                key: round(summary[key], 4) for key in ("median", "p95", "p99")
            }
    result["processes_spawned"] = spawned[0]
    result["commands"] = 1 + calls * len(REQUESTS)
    return result


def main() -> int:
    """Measure both engines and print JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calls", type=int, default=300)
    args = parser.parse_args()
    if args.calls < 1:
        parser.error("--calls must be at least 1")

    server = new_server()
    server.new_session("bench", window_name="w0")
    server.new_session("bench2", window_name="w0")
    try:
        out: dict[str, t.Any] = {
            "tmux": SubprocessEngine.for_server(server).tmux_version(),
            "calls": args.calls,
            "subprocess": measure(SubprocessEngine.for_server(server), args.calls),
        }
        with ControlModeEngine.for_server(server) as control:
            out["control"] = measure(control, args.calls)
    finally:
        with contextlib.suppress(Exception):
            server.kill()
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
