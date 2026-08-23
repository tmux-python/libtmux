#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["libtmux"]
#
# [tool.uv.sources]
# libtmux = { path = "../..", editable = true }
# ///
"""Measure what libtmux's current API costs against a live tmux server.

This is the baseline, not a comparison. It exercises only what ships today --
the classic :class:`~libtmux.Server` object hierarchy and the command execution
seam -- so its numbers are the reference any later transport has to beat.

Three quantities, deliberately kept apart:

- **construction**: wall time to build the requested topology.
- **enumeration**: wall time for ``server.sessions`` / ``.windows`` / ``.panes``,
  the classic hierarchy read, with the row counts it returned.
- **dispatch**: wall time per :class:`~libtmux.engines.base.CommandRequest`
  through :class:`~libtmux.engines.subprocess.SubprocessEngine`, alongside the
  tmux commands those requests carried.

The last pair is the point. A request and a tmux command are not the same
thing: a command group rides several commands inside one dispatch, and
:class:`~libtmux.engines.instrumentation.CountingSink` reports the difference
as ``inlined``. Measuring them separately is what keeps a later change that
merely moves work between them from reading as a win.

Isolation, shape parsing, and statistics come from :mod:`primitives`, so
this benchmark and the engine benchmark above it measure with one ruler.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import pathlib
import sys
import time
import typing as t

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from primitives import (
    build_classic,
    new_server,
    parse_shape,
    summarize,
    uniq,
)

from libtmux.engines import (
    CommandRequest,
    CommandSeparator,
    CountingSink,
    SubprocessEngine,
    instrument,
)

if t.TYPE_CHECKING:
    from libtmux.server import Server


def _ms(samples_ns: list[int]) -> dict[str, float]:
    """Summarise nanosecond samples as milliseconds, using the shared ruler."""
    return {
        key: round(value, 4)
        for key, value in summarize([value / 1e6 for value in samples_ns]).items()
    }


def build_topology(server: Server, *, sessions: int, shape: str) -> dict[str, int]:
    """Build *sessions* sessions of *shape*, timing the whole construction.

    Each session is built by :func:`primitives.build_classic`, the same
    routine the engine benchmark uses for its ``classic`` lane, so a number
    here and a number there describe the same work.
    """
    wins, panes = parse_shape(shape)
    started_ns = time.perf_counter_ns()
    for _ in range(sessions):
        build_classic(server, uniq(), wins, panes)
    construction_ns = time.perf_counter_ns() - started_ns
    # `sessions` counts what the server holds, which includes the keepalive
    # session new_server() never kills; `built` counts what this run created.
    # Reporting only the first would overstate the topology a shape asked for.
    return {
        "construction_ns": construction_ns,
        "built": sessions,
        "sessions": len(server.sessions),
        "windows": sum(len(s.windows) for s in server.sessions),
    }


def enumerate_classic(server: Server, *, rounds: int) -> dict[str, t.Any]:
    """Time the classic hierarchy read, the API that ships today."""
    per_level: dict[str, list[int]] = {"sessions": [], "windows": [], "panes": []}
    counts: dict[str, int] = {}
    for _ in range(rounds):
        for level in ("sessions", "windows", "panes"):
            started_ns = time.perf_counter_ns()
            rows = list(getattr(server, level))
            per_level[level].append(time.perf_counter_ns() - started_ns)
            counts[level] = len(rows)
    return {
        "rows": counts,
        "timings": {level: _ms(v) for level, v in per_level.items()},
    }


def dispatch_through_seam(server: Server, *, rounds: int) -> dict[str, t.Any]:
    """Time requests through the seam, counting requests against tmux commands.

    The grouped request is the one that matters: it carries two tmux commands
    in a single dispatch, so ``requests`` and ``tmux_commands`` diverge and
    ``inlined`` reports by how much.
    """
    counts = CountingSink()
    engine = instrument(SubprocessEngine.for_server(server), counts)

    plain = CommandRequest.from_args("list-panes", "-a")
    grouped = CommandRequest.from_args(
        "set-option",
        "-g",
        "@bench",
        "1",
        CommandSeparator(";"),
        "show-options",
        "-g",
    )

    plain_ns: list[int] = []
    grouped_ns: list[int] = []
    for _ in range(rounds):
        started_ns = time.perf_counter_ns()
        engine.run(plain)
        plain_ns.append(time.perf_counter_ns() - started_ns)

        started_ns = time.perf_counter_ns()
        engine.run(grouped)
        grouped_ns.append(time.perf_counter_ns() - started_ns)

    return {
        "plain": _ms(plain_ns),
        "grouped": _ms(grouped_ns),
        "observed": {
            "requests": counts.requests,
            "tmux_commands": counts.tmux_commands,
            "inlined": counts.inlined,
            "elapsed_ms": round(counts.elapsed_ns / 1e6, 3),
        },
    }


def run(*, sessions: int, shape: str, rounds: int) -> dict[str, t.Any]:
    """Measure one shape end to end and return the machine-readable result."""
    server = new_server()
    try:
        topology = build_topology(server, sessions=sessions, shape=shape)
        return {
            "shape": {"sessions": sessions, "shape": shape, "rounds": rounds},
            "topology": {
                "built": topology["built"],
                "sessions": topology["sessions"],
                "windows": topology["windows"],
                "construction_ms": round(topology["construction_ns"] / 1e6, 3),
            },
            "enumeration": enumerate_classic(server, rounds=rounds),
            "dispatch": dispatch_through_seam(server, rounds=rounds),
        }
    finally:
        with contextlib.suppress(Exception):
            server.kill()


def main() -> int:
    """Parse arguments, measure, and print the result as JSON."""
    parser = argparse.ArgumentParser(description="Benchmark libtmux's current API.")
    parser.add_argument("--sessions", type=int, default=2)
    parser.add_argument("--shape", default="2x1", help="windows x panes, e.g. 8x4")
    parser.add_argument("--rounds", type=int, default=10)
    args = parser.parse_args()

    if min(args.sessions, args.rounds) < 1:
        parser.error("--sessions and --rounds must both be at least 1")
    wins, panes = parse_shape(args.shape)
    if min(wins, panes) < 1:
        parser.error("--shape must name at least one window and one pane")

    print(
        json.dumps(
            run(sessions=args.sessions, shape=args.shape, rounds=args.rounds),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
