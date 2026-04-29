#!/usr/bin/env python
"""Compare two pstats files; print top-N functions sorted by Δ cumtime.

Replaces the broken ``--diff-flamegraph`` workflow in Python 3.15.0a8
(see SKILL.md "Known issue" section). Output is markdown so it can be
pasted directly into PRs, issues, or chat.

Usage:
    python diff-pstats.py BASELINE.pstats CURRENT.pstats [--top 30]

Output format:
    | function | baseline (s) | current (s) | Δ (s) | Δ% |
    |---|---:|---:|---:|---:|
    | `path/to/file.py:NNN(funcname)` | 1.234 | 2.345 | +1.111 | +90.0% |
    ...

Sorted by absolute Δ cumtime descending — the biggest movers first,
regardless of direction. Functions only present in one profile show
"—" in the Δ% column.
"""

from __future__ import annotations

import argparse
import pathlib
import pstats
import sys


def collect_cumtime(path: str) -> dict[str, float]:
    """Return a ``{function_label: cumulative_time}`` mapping for one pstats file.

    The ``stats`` attribute on ``pstats.Stats`` is a private dict keyed
    by ``(filename, lineno, name)`` 3-tuples. We flatten the key to a
    readable label suitable for printing in a markdown table.
    """
    stats = pstats.Stats(path)
    out: dict[str, float] = {}
    for func, (_cc, _nc, _tt, ct, _callers) in stats.stats.items():
        filename, lineno, name = func
        label = f"{filename}:{lineno}({name})"
        out[label] = ct
    return out


def main() -> int:
    """Parse args, build the diff table, print to stdout."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("baseline", help="path to baseline .pstats file")
    p.add_argument("current", help="path to current .pstats file")
    p.add_argument(
        "--top",
        type=int,
        default=30,
        help="max rows to print (default: 30)",
    )
    args = p.parse_args()

    for path_str, label in ((args.baseline, "baseline"), (args.current, "current")):
        if not pathlib.Path(path_str).is_file():
            sys.stderr.write(f"error: {label} file not found: {path_str}\n")
            return 2

    base = collect_cumtime(args.baseline)
    cur = collect_cumtime(args.current)

    keys = set(base) | set(cur)
    rows: list[tuple[str, float, float, float, float]] = []
    for k in keys:
        b, c = base.get(k, 0.0), cur.get(k, 0.0)
        delta = c - b
        pct = (delta / b * 100) if b > 0 else float("inf")
        rows.append((k, b, c, delta, pct))

    rows.sort(key=lambda r: abs(r[3]), reverse=True)

    print(f"# pstats diff (top {args.top} by |Δ cumtime|)")
    print()
    print(f"- baseline: `{args.baseline}`")
    print(f"- current:  `{args.current}`")
    print()
    print("| function | baseline (s) | current (s) | Δ (s) | Δ% |")
    print("|---|---:|---:|---:|---:|")
    for k, b, c, d, pct in rows[: args.top]:
        pct_str = "—" if pct == float("inf") else f"{pct:+.1f}%"
        print(f"| `{k}` | {b:.3f} | {c:.3f} | {d:+.3f} | {pct_str} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
