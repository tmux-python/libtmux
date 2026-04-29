---
name: engine-benchmark
description: Use when the user wants to compare full-suite test wall time across libtmux's three protocol engines (subprocess, imsg, control_mode) on libtmux and/or tmuxp — "benchmark engines", "compare engine wall time", "hyperfine engines", "test suite engine speed", "engine speedup table", "imsg vs subprocess wall", "control_mode wall", "engine ranking", "end-to-end engine benchmark", "full-suite engine comparison". Wraps hyperfine's parameter scan to run all three engines per repo, parses the JSON, and prints a unified markdown table plus an Insights section flagging speedup ratios and σ noise. SKIP for intra-run profiling questions ("where is time spent", flamegraph, heatmap, hot path, microbench) — those go to libtmux-profiler.
---

# Full-suite engine benchmark — `uv run pytest` × 3 engines × hyperfine

This skill answers one question, repeatably: **which engine ships
the test suite fastest?** It runs the entire libtmux and/or tmuxp
test suite under each of the three protocol engines, captures the
wall time with hyperfine (mean ± σ across N runs after a warmup),
and prints a paste-ready markdown table plus a short Insights
section.

It complements [`libtmux-profiler`](../libtmux-profiler/SKILL.md):
this skill measures *aggregate* wall across the whole suite;
`libtmux-profiler` answers *where the difference comes from* via
flamegraphs, pstats, and per-call microbenches. When the table
here shows a gap, the natural follow-up is a profiler session.

## What this measures

* Full pytest suite wall time, end to end, including pytest
  startup, fixture setup, and teardown.
* Mean ± σ + median + min + max across N measured runs.
* Speedup ratio against a chosen baseline engine (default
  `subprocess`).

What it does **not** measure: per-call latency (use
`libtmux-profiler`'s single-call microbench), CPU vs wall split
(use `libtmux-profiler` with `--mode cpu`), or library-internal
hot paths (use `libtmux-profiler`'s pstats top-N).

## Prerequisites

1. **`hyperfine` on PATH.** One of:

   ```console
   $ cargo install hyperfine
   ```

   ```console
   $ apt install hyperfine  # debian/ubuntu
   ```

   The script bails with a clear install hint if missing.

2. **Two repos checked out at expected paths** (override with
   env vars if your layout differs):

   * `~/work/python/libtmux-protocol-engines` — override:
     `BENCH_LIBTMUX_PATH`
   * `~/work/python/tmuxp-libtmux-protocol` — override:
     `BENCH_TMUXP_PATH`

   Missing repos are skipped with a warning, not a crash — pass
   `--repos libtmux` (or `--repos tmuxp`) to bench just one.

## Quick recipe

```console
$ python3 .claude/skills/engine-benchmark/scripts/bench-suites.py
```

Defaults to: 1 warmup + 5 measured runs per (repo, engine), both
repos, `subprocess` as the speedup-ratio baseline, artifacts in
`/tmp/bench-engines/<YYYY-MM-DD-HH-MM-SS>/`. Total wall ≈ 6–10
minutes depending on host.

## CLI surface

```console
$ python3 .claude/skills/engine-benchmark/scripts/bench-suites.py --help
```

| Flag | Default | Purpose |
|------|---------|---------|
| `--repos` | `libtmux tmuxp` | Subset of repos to bench. |
| `--warmup` | `1` | Hyperfine warmup runs (fills kernel cache + Python imports). |
| `--runs` | `5` | Measured runs per (repo, engine). |
| `--outdir` | `/tmp/bench-engines/<timestamp>` | Where to write per-repo `.json` + `.md`. |
| `--baseline-engine` | `subprocess` | Reference for the speedup column. Use `imsg` to compare imsg vs control_mode directly. |
| `--extra-pytest-args` | `""` | Forwarded to pytest. Example: `--extra-pytest-args="-k workspace"` for a partial-suite bench. |

## Worked example output

The skill produces a unified table like this (numbers from a real
run on `libtmux-protocol-engines@71b53457` +
`tmuxp-libtmux-protocol@11a3c830`):

```markdown
## Engine benchmark — `uv run pytest` full suite, 1 warmup + 5 measured runs

| Repo | Engine | Mean ± σ | Median | Min | Max | vs subprocess |
|------|--------|---------:|-------:|----:|----:|-----------------:|
| **libtmux** | subprocess | 42.97 s ± 0.84 | 42.92 s | 42.15 s | 44.18 s | 1.00× |
| **libtmux** | imsg | 36.72 s ± 1.06 | 36.10 s | 35.89 s | 38.14 s | **1.17× faster** |
| **libtmux** | control_mode | 22.23 s ± 0.47 | 22.08 s | 21.72 s | 22.85 s | **1.93× faster** |
| **tmuxp** | subprocess | 29.21 s ± 0.38 | 29.32 s | 28.58 s | 29.52 s | 1.00× |
| **tmuxp** | imsg | 26.86 s ± 1.19 | 26.28 s | 25.72 s | 28.15 s | **1.09× faster** |
| **tmuxp** | control_mode | 24.91 s ± 1.72 | 24.26 s | 23.83 s | 27.98 s | **1.17× faster** |

## Insights

- **libtmux**: imsg is **1.17× faster** than subprocess (43.0 s → 36.7 s).
- **libtmux**: control_mode is **1.93× faster** than subprocess (43.0 s → 22.2 s).
- **tmuxp**: imsg is **1.09× faster** than subprocess (29.2 s → 26.9 s).
- **tmuxp**: control_mode is **1.17× faster** than subprocess (29.2 s → 24.9 s).
- **control_mode speedup compresses** from 1.93× on `libtmux` to 1.17× on `tmuxp` — likely shell-readiness wait absorbing the engine win (see `libtmux-profiler` worked example).

_Artifacts: /tmp/bench-engines/2026-04-29-15-12-00/{repo}.{json,md}_
```

The "compresses" insight is the diagnostic landmark: when the
same engine shows different speedups across the two repos, the
slower repo is shell-bound (its work waits on the spawned shell
to draw its prompt rather than on tmux protocol cost). That's
exactly the case `libtmux-profiler`'s [worked
example](../libtmux-profiler/SKILL.md#worked-example----what-we-discovered-with-this-exact-tooling)
documents — engine choice cannot compress shell startup; it can
only choose where to account for it. Click through to the
profiler skill when this insight fires; it points at
`tmuxp/workspace/builder.py:_wait_for_pane_ready` as the
absorbing wait.

## Cross-references

* When the gap is interesting and you want to know *why*:
  → [`libtmux-profiler/SKILL.md`](../libtmux-profiler/SKILL.md),
  specifically the **libtmux-direct A/B engine comparison** recipe
  for engine-bound flamegraphs and the **automated pstats diff**
  workflow for the structured per-function delta.
* When the table shows σ-noise warnings (>10 % of mean): rerun on
  a quieter system, or bump `--runs` from 5 → 7. Hyperfine's
  outlier detection already calls these out, but the script's
  Insights section surfaces them so they're hard to miss.

## Pitfalls

* **Pre-existing test failures inflate exit codes.** Three
  env-bound tests fail on this WSL2 host
  (`tests/test_server.py::test_no_server_*`); under
  `--engine=control_mode` a `tests/test_common.py` collection
  error also surfaces. The script invokes `hyperfine -i` so
  non-zero pytest exits don't bork the sweep — wall-time
  comparison stays valid as long as the failing set is stable
  across engines (it is, on this branch). If you fix one of the
  failures upstream, no action needed here.
* **VIRTUAL_ENV inheritance.** Running the script from inside
  libtmux's venv (e.g. an active `.venv` in the parent shell)
  leaks `VIRTUAL_ENV=...libtmux/.venv` into the tmuxp subprocess
  and `uv` warns. The script explicitly unsets `VIRTUAL_ENV`
  when invoking the tmuxp benchmark to avoid that.
* **First run on a cold host can be 2–5 % slower.** That's the
  page cache / Python bytecode compile / `import libtmux` cost.
  `--warmup 1` (the default) drops it; bump to `--warmup 2` if
  σ stays above 10 %.
* **Hyperfine's built-in summary always picks the fastest as
  reference.** That's why this skill re-parses the JSON: the
  `vs <baseline-engine>` column reports against your chosen
  baseline (subprocess by default), so the table reads as
  "improvement over the no-tuning baseline" rather than "how
  much slower than the fastest".

## Output directory layout

```
/tmp/bench-engines/
└── <YYYY-MM-DD-HH-MM-SS>/      e.g. 2026-04-29-15-12-00
    ├── libtmux.json            hyperfine --export-json
    ├── libtmux.md              hyperfine --export-markdown (per-repo)
    ├── tmuxp.json
    └── tmuxp.md
```

The `.md` files are hyperfine's per-repo three-row tables (raw
output, no speedup column); the script's stdout is the unified
six-row table with the speedup column. Keep `.json` if you want
to feed it into another comparison later — the schema is stable
across hyperfine 1.x.
