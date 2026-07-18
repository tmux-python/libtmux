---
name: benchmarking-engine-builds
description: Use when measuring or profiling how fast libtmux.experimental engines build tmux workspaces — comparing classic vs subprocess/control_mode/imsg/mock/pipelined, chasing a build-latency regression, reading percentile grids, or finding where a control-mode build spends its time (cProfile). Runs scripts/bench_engines.py hermetically on throwaway sockets.
---

# Benchmarking engine builds

## Overview

`scripts/bench_engines.py` times how long each experimental engine takes to
build a tmux session structure (`W` windows × `P` panes-per-window), sweeping
shapes × engines × wait-modes and reporting min/avg/median/p90/p95/p99/max.

**Hermetic and safe to run beside a live tmux session:** every server gets its
own socket under a throwaway `mkdtemp` dir, `TMUX` is unset before libtmux is
imported, and an `atexit` hook kills every spawned server. The default tmux
server is never contacted.

It is a PEP 723 script — **always launch it with `uv run`**, never `python`, or
its inline deps (`rich`, `typer`, editable `libtmux`) won't resolve.

## When to use

- Comparing engine build cost (which engine is fastest for a given shape).
- Checking whether a change to the ops/plan/engine layer moved build latency.
- Reading percentile spread (is p99 blowing out?) rather than a single number.
- Locating the hot path inside one engine's build (`profile` → cProfile cumtime).

## Quick reference

Run from the repo root.

| Command | What it does |
|---|---|
| `uv run scripts/bench_engines.py run` | full grid (the clean signal) |
| `uv run scripts/bench_engines.py profile --engine control_mode --shape 8x4` | cProfile one engine, print slowest by cumtime |
| `uv run scripts/bench_engines.py cell control_mode 8x4` | one isolated build (for wrapping in hyperfine) |

`run` flags: `--shapes 1x1,1x4,3x3,5x4,8x4`, `--engines classic,subprocess,control_mode,imsg,mock,pipelined`,
`--wait` (ALSO measure with shell-readiness wait), `--runs 20`, `--warmup 3`,
`--json-out grid.json`. Shape is `windows x panes-per-window`.

Engines: `classic` (Server/Session/Window/Pane API) · `subprocess` (one fork
per op) · `control_mode` (one persistent `tmux -C`) · `imsg` (AF_UNIX one-shot) ·
`mock` (offline, in-memory Python floor) · `pipelined` (prototype: batch
independent creates via `run_batch`).

## Reading the results

- **`control_mode` is the fastest shipped engine** (~21× classic at 32 panes)
  because it avoids a per-op `tmux` fork. `pipelined` edges it (~1.4×) by
  batching independent creates into ~3 round-trips.
- **Builds are tmux-server-bound, not round-trip-bound** — one shell fork per
  pane dominates, so cutting round-trips helps less than the count implies.
  `mock` (~1–2 ms) is the pure-Python floor: the plan/compile layer is
  negligible; the time is tmux.
- **`profile` shows ~68% in `select.epoll.poll`** inside `_read_blocks`: each
  created id is read back before the next op targets it. Latency-bound.

## Common mistakes

- Running with `python` instead of `uv run` — PEP 723 deps don't resolve.
- **Comparing `--wait` against no-wait across engines.** Shell startup
  (~0.8–2.1 s) dwarfs a fast build, so the ~20× engine win collapses to ~1.5×
  once both sides wait. A classic-that-waits vs a builder-that-doesn't is
  apples-to-oranges (this is the bogus "~79×" trap). Compare like with like.
- Trusting hyperfine whole-process wall time over the in-process grid — Python
  startup + import dwarfs a 3 ms build and understates the builder. The
  in-process `run` grid is the clean signal.
- Expecting `mock` under `--wait`: it has no real panes and is skipped.

## Results & reproduction

Committed results live in `scripts/bench-results/`: `RESULTS.md` (narrative +
tables), `grid.json` (no-wait grid), `wait.json` (wait comparison). Regenerate
the raw JSON with `--json-out`.
