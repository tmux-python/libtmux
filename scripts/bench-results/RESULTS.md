# libtmux engine build-benchmark — results

Produced by `scripts/bench_engines.py` (a hermetic PEP 723 grid runner) plus a
one-off hyperfine end-to-end run. All builds are isolated: per-run sockets under
a throwaway dir, `TMUX` unset, servers killed on exit — the default tmux server
is never contacted. Reproduce with:

```console
$ uv run scripts/bench_engines.py run
$ uv run scripts/bench_engines.py run --engines classic,control_mode,pipelined --wait
$ uv run scripts/bench_engines.py profile --engine control_mode --shape 8x4
```

Raw data: `grid.json` (no-wait grid), `wait.json` (wait comparison).

## Engine grid — in-process build, median ms (xN vs classic), 20 runs

Shape = `windows x panes-per-window`. Structural builds (no shell-readiness wait).

| engine | 1x1 | 1x4 | 3x3 | 5x4 | 8x4 |
|---|--:|--:|--:|--:|--:|
| classic (Server/Session/Window/Pane) | 22.0 | 169.4 | 452.5 | 1442.2 | 3497.2 |
| builder / subprocess | 23.0 | 42.8 | 86.9 | 246.7 | 428.8 (8x) |
| builder / imsg | 20.6 | 31.1 | 62.6 | 153.4 | 262.0 (13x) |
| builder / control_mode | 2.5 | 9.4 | 26.5 | 103.3 | 166.7 (21x) |
| **pipelined (prototype)** | **1.4** | **7.9** | **20.2** | **65.3** | **115.7 (30x)** |
| mock (offline, in-memory) | 0.1 | 0.1 | 0.3 | 1.3 | 1.5 |

Full percentiles at 8x4 (ms):

| engine | min | avg | median | p90 | p95 | p99 | max |
|---|--:|--:|--:|--:|--:|--:|--:|
| classic | 2192 | 3404 | 3497 | 3931 | 4077 | 4432 | 4432 |
| subprocess | 358 | 426 | 429 | 479 | 481 | 487 | 487 |
| imsg | 222 | 283 | 262 | 342 | 421 | 455 | 455 |
| control_mode | 118 | 180 | 167 | 215 | 216 | 398 | 398 |
| pipelined | 97 | 123 | 116 | 156 | 165 | 194 | 194 |
| mock | 1 | 2 | 2 | 2 | 2 | 2 | 2 |

Reads:

- **control_mode** (one persistent `tmux -C`, no per-op fork) is the fastest
  shipped engine: 21x classic at 32 panes.
- **imsg** (AF_UNIX one-shot per call) sits between subprocess and control_mode;
  its per-call handshake makes tiny builds no faster than classic.
- **pipelined** (prototype: batch independent creates into ~3 `run_batch`
  round-trips instead of ~34) is fastest overall, ~1.4x over control_mode. Not
  the 11x the round-trip count implies, because the build is **tmux-server-bound**
  (one shell fork per pane), not round-trip-bound. `mock` (offline, 1.5 ms)
  is the Python floor: the plan/compile layer is negligible; the time is tmux.

## With vs without shell-readiness wait

`wait.json`, 10 runs. "wait" polls each pane until its shell has drawn a prompt.

| shape | engine | nowait median | wait median | wait penalty | speedup vs classic |
|---|---|--:|--:|--:|--:|
| 1x4 | classic | 217.6 | 1134.5 | 5.2x | 1.0x |
| 1x4 | control_mode | 9.4 | 865.2 | 92x | 23.1x -> 1.3x |
| 1x4 | pipelined | 9.0 | 1004.3 | 112x | 24.3x -> 1.1x |
| 5x4 | classic | 1365.6 | 3252.7 | 2.4x | 1.0x |
| 5x4 | control_mode | 73.1 | 2194.5 | 30x | 18.7x -> 1.5x |
| 5x4 | pipelined | 66.6 | 2123.3 | 32x | 20.5x -> 1.5x |

**The engine win only exists when nobody waits for shells.** Shell startup
(~0.8-2.1 s) dominates a fast build (30-112x penalty) but barely moves the slow
classic path (2-5x), so the ~20x engine advantage collapses to ~1.5x once both
sides wait. Comparing a classic-that-waits against a builder-that-doesn't is
apples-to-oranges (this is why an earlier ad-hoc run reported ~79x).

## Profile — where a control_mode build spends time (32 panes x5)

~200 ms/build; **68% is `select.epoll.poll`** in `control_mode._read_blocks` —
one round-trip per created id (each new window/pane id read back before the next
op targets it). Round-trip-latency bound, not CPU/Python bound.

## Whole-process wall time (hyperfine, SubprocessEngine, end-to-end)

For reference, whole-script wall time (Python start + import + build + teardown)
on `SubprocessEngine`, 50 runs: classic simple 210 ms / large 6764 ms; builder
simple 453 ms / large 1692 ms. End-to-end on the *slowest* engine understates the
builder (startup dwarfs a 3 ms build) — the in-process grid above is the clean
signal. Prefer `control_mode` and in-process timing to measure build cost.

## Build-cost factorial — `matrix`

The `matrix` subcommand isolates which of four independent choices drives build
cost, sweeping them as a factorial: **async** {sync, async} × **transport**
{subprocess, control_mode} × **planner** {imperative, plan-seq, plan-fold} ×
**workspace** {hand `LazyPlan`, declarative `Workspace`}. Because a declarative
workspace compiles to a lazy plan, the valid expression layers are five —
`imperative`, `plan-seq`, `plan-fold`, `ws-seq`, `ws-fold` — crossed with 2
transports × 2 modes = 20 cells, against a `classic` reference. Reproduce:

```console
$ uv run scripts/bench_engines.py matrix --shapes 1x4,3x3,5x4
```

`mock` is absent from the table by design: it is the offline correctness
**oracle**, not a results row. `matrix --check` (default on) and the standalone
`contract` subcommand assert every layer × mode renders identical tmux argv to
mock, so the benchmark doubles as an ops-language contract test:

```console
$ uv run scripts/bench_engines.py contract
```

Illustrative 1×4 snapshot (small run; absolute ms are machine-dependent — the
ratios are the portable signal):

| layer × transport × mode | median ms | vs classic |
|---|--:|--:|
| classic (reference) | 168.7 | 1.0x |
| ws-fold · control_mode · sync | 7.8 | 21.5x |
| plan-fold · control_mode · sync | 6.3 | 26.8x |
| imperative · control_mode · async | 7.0 | 24.0x |
| ws-fold · subprocess · sync | 30.7 | 5.5x |

Reads: transport dominates (control_mode ~4-5× subprocess); planner choice
(imperative → plan-seq → plan-fold) and the declarative-workspace compile move
build cost only marginally — the plan/compile layer is cheap, the time is tmux.
Single-build async ≈ sync (a linear build serializes either way).

## Concurrency — `concurrency`

Async's real lever is not single-build latency but overlap. `concurrency`
builds K independent sessions sync-serial vs `asyncio.gather` over one
connection:

```console
$ uv run scripts/bench_engines.py concurrency --transport control_mode --k 4
```

Over one `control_mode` connection, async-gather runs ~2.4× the sync-serial
wall time at K=4 — the persistent connection multiplexes the K builds'
round-trips instead of paying them end-to-end. This is the win the single-build
matrix structurally cannot show.
