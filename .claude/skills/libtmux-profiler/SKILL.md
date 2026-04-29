---
name: libtmux-profiler
description: Use when the user wants to profile or benchmark libtmux/tmuxp performance — investigating "where is the lag", "why is the test suite slow", flamegraphs, heatmaps, hot-spot analysis, A/B comparing imsg vs subprocess engines, single-call microbenchmarks, or pstats diffs. TRIGGER when phrases include "profile libtmux", "profile tmuxp", "tachyon", "flamegraph", "heatmap", "where is the bottleneck", "where is the lag", "compare engines", "imsg vs subprocess flamegraph", "why are imsg and subprocess the same speed", "benchmark libtmux", "benchmark tmuxp", "how fast is", "microbench", "single-call speed", "per-call timing", or "diff pstats". Uses Python 3.15's stdlib profiling.sampling module (Tachyon) plus a pstats-arithmetic diff helper for structured comparisons. SKIP for unrelated profiling questions or projects outside libtmux-protocol/tmuxp-libtmux-protocol.
---

# Profiling libtmux & tmuxp with Tachyon

Tachyon is Python 3.15's `profiling.sampling` stdlib module: a statistical
sampling profiler that reads stack frames externally with near-zero target
overhead. It produces interactive flamegraphs, line-level heatmaps,
Gecko-compatible call trees, and pstats output — no third-party tooling
required.

## Prerequisites

1. **Python 3.15.0a8** must be installed via mise:
   ```console
   $ mise install python@3.15.0a8
   ```
   Both `~/work/python/libtmux-protocol/.tool-versions` and
   `~/work/python/tmuxp-libtmux-protocol/.tool-versions` already declare it.

2. **A `.venv-3.15` venv** in the target repo with libtmux/tmuxp installed
   editable. If missing, run the bootstrap script:
   ```console
   $ bash ~/work/python/libtmux-protocol/.claude/skills/libtmux-profiler/scripts/setup-tachyon-venv.sh
   ```
   The script is idempotent — safe to re-run; it skips work when the venv
   already exists.

3. **Verify Tachyon is reachable:**
   ```console
   $ ./.venv-3.15/bin/python -m profiling.sampling --help
   ```

## Output directory convention

Every profiling session goes into a structured path:

```
/tmp/py-profiling/<YYYY-MM-DD-HH-MM-SS>/<project>/<branch>/<session-name>/
```

This keeps artifacts organized across many sessions, surfaces the project
and branch in the path, and timestamps each run for easy chronological
sorting. The included `init-profile-session.sh` helper builds this path,
creates a per-session `README.md` with metadata (timestamp, repo root,
branch, HEAD short-sha, Python version), and prints the absolute path:

```console
$ PROFILE_DIR=$(bash ~/work/python/libtmux-protocol/.claude/skills/libtmux-profiler/scripts/init-profile-session.sh engine-ab-test)
$ echo "$PROFILE_DIR"
/tmp/py-profiling/2026-04-28-11-20-25/tmuxp-libtmux-protocol/libtmux-protocol/engine-ab-test/
```

**Always `cd` into the target repo first** — the script reads
`git rev-parse --show-toplevel` from `$PWD`, so the project name and branch
are auto-detected.

## Which recipe should I use?

| if the question is... | use |
|---|---|
| "tmuxp test suite is slow, why?" | **Quick recipe — tmuxp+engines** (below) |
| "libtmux engine A/B — where imsg actually wins" | **Recipe — libtmux-direct A/B** |
| "how fast is `server.X()` under each engine?" | **Recipe — single-call microbenchmark** |
| "structured comparison of two profiles" | **Workflow — automated pstats diff** |
| "pstats top-N to terminal, no browser" | **Workflow — pstats top-N** |
| "what hot lines in this function?" | **Workflow — heatmap** |
| "test is hanging, what's it doing?" | **Workflow — live TUI / attach** |

The first three recipes form a complementary set. The tmuxp Quick
Recipe is **shell-bound** — it shows the engine-vs-shell-wait swap
documented in the Worked Example, but masks per-call engine deltas
because tmuxp's `_wait_for_pane_ready` polling loop absorbs imsg's
savings. The libtmux-direct A/B and single-call microbenchmark recipes
are **engine-bound** — no shell-readiness polling, so imsg's per-call
advantage shows up clearly (typically 25-55% on `has_session`-class
operations).

## Quick recipe — A/B engine comparison (the headline use case)

This is what to run when the question is "where does imsg differ from
subprocess?" or "why is the bench so close?". The workflow:

1. Capture each engine's run as a Tachyon `.bin` binary (cheap, replay-able)
2. Replay each binary into a flamegraph + pstats
3. Open both flamegraphs in browser tabs and search for the smoking gun

```console
$ cd ~/work/python/tmuxp-libtmux-protocol
$ PROFILE_DIR=$(bash ~/work/python/libtmux-protocol/.claude/skills/libtmux-profiler/scripts/init-profile-session.sh engine-ab)

# Capture subprocess baseline (binary).
$ SHELL=/bin/sh LIBTMUX_ENGINE=subprocess ./.venv-3.15/bin/python \
    -m profiling.sampling run --binary -r 5khz \
    -o "$PROFILE_DIR/subprocess.bin" \
    -m pytest tests/workspace/test_builder.py --no-cov -p no:randomly --engine=subprocess

# Capture imsg (binary).
$ SHELL=/bin/sh LIBTMUX_ENGINE=imsg ./.venv-3.15/bin/python \
    -m profiling.sampling run --binary -r 5khz \
    -o "$PROFILE_DIR/imsg.bin" \
    -m pytest tests/workspace/test_builder.py --no-cov -p no:randomly --engine=imsg

# Replay each binary to a flamegraph and to pstats.
$ for engine in subprocess imsg; do
    ./.venv-3.15/bin/python -m profiling.sampling replay \
      "$PROFILE_DIR/$engine.bin" --flamegraph -o "$PROFILE_DIR/$engine.html"
    ./.venv-3.15/bin/python -m profiling.sampling replay \
      "$PROFILE_DIR/$engine.bin" --pstats -o "$PROFILE_DIR/$engine.pstats"
  done

# Show side-by-side top-30 from each pstats:
$ ./.venv-3.15/bin/python -c "
import pstats
for label, path in (('SUBPROCESS', '$PROFILE_DIR/subprocess.pstats'),
                    ('IMSG',       '$PROFILE_DIR/imsg.pstats')):
    print(f'\n=== {label} ===')
    pstats.Stats(path).sort_stats('cumulative').print_stats(20)
"
```

Open `$PROFILE_DIR/subprocess.html` and `$PROFILE_DIR/imsg.html` in
adjacent browser tabs. Use the in-page search (Ctrl+F or the flamegraph's
own search box) to locate `_wait_for_pane_ready`, `Popen.communicate`,
and `selectors.poll` — these are the diagnostic landmarks for the
engine-vs-shell-wait swap explained in **Worked example** below.

**Why `SHELL=/bin/sh`:** aligns the runtime env with the test config
(`default-shell /bin/sh`) so tmuxp's `os.getenv("SHELL")`-reading code
paths agree with what tmux actually spawns. Without it,
`test_automatic_rename_option` flakes.

**Why `-p no:randomly`:** ensures both runs visit tests in identical
order, so frame-by-frame comparison between flamegraphs makes sense.

## Recipe — libtmux-direct A/B engine comparison

This is the counterpart to the tmuxp Quick Recipe above. **Use this
when you want to see imsg's per-call advantage clearly** — libtmux's
own tests don't go through tmuxp's workspace builder, so there's no
`_wait_for_pane_ready` poll loop to mask the tmux-command savings.
Expect a meaningful wall delta in imsg's favor (~10-30% depending on
test mix).

**Recommended target:** `tests/test_server.py` — 47 tests, 21 use the
engine-bound fixtures, no `time.sleep` calls, ~8-12s per engine.
Alternatives: `tests/test_session.py` (28 tests, 79% fixture density)
for broader API coverage; a single test like
`tests/test_server.py::test_no_server_is_alive` for narrower scope.

```console
$ cd ~/work/python/libtmux-protocol
$ PROFILE_DIR=$(bash ~/work/python/libtmux-protocol/.claude/skills/libtmux-profiler/scripts/init-profile-session.sh libtmux-direct-ab)

# Capture both engines as binaries.
$ for engine in subprocess imsg; do
    SHELL=/bin/sh LIBTMUX_ENGINE=$engine ./.venv-3.15/bin/python \
      -m profiling.sampling run --binary -r 5khz \
      -o "$PROFILE_DIR/$engine.bin" \
      -m pytest tests/test_server.py --no-cov -p no:randomly --engine=$engine
  done

# Replay each to flamegraph + pstats.
$ for engine in subprocess imsg; do
    ./.venv-3.15/bin/python -m profiling.sampling replay \
      "$PROFILE_DIR/$engine.bin" --flamegraph -o "$PROFILE_DIR/$engine.html"
    ./.venv-3.15/bin/python -m profiling.sampling replay \
      "$PROFILE_DIR/$engine.bin" --pstats -o "$PROFILE_DIR/$engine.pstats"
  done

# Structured diff (see "Workflow — automated pstats diff" below).
$ ./.venv-3.15/bin/python \
    ~/work/python/libtmux-protocol/.claude/skills/libtmux-profiler/scripts/diff-pstats.py \
    "$PROFILE_DIR/subprocess.pstats" "$PROFILE_DIR/imsg.pstats" --top 30
```

The diff-pstats output should show `SubprocessEngine.run`,
`Popen.communicate`, and `selectors.poll` collapsing to 0 in the
imsg column, with `ImsgEngine.run` and the imsg socket-transport
methods appearing as net-new entries. That swap is the headline
result.

## Recipe — single-call microbenchmark

For "how fast is `server.has_session()` under each engine?"-shaped
questions. Skips the test framework entirely and runs a tight loop
against a real tmux server using a pre-defined registry of bench
targets.

```console
$ cd ~/work/python/libtmux-protocol
$ PROFILE_DIR=$(bash ~/work/python/libtmux-protocol/.claude/skills/libtmux-profiler/scripts/init-profile-session.sh microbench-has-session)

$ for engine in subprocess imsg; do
    SHELL=/bin/sh LIBTMUX_ENGINE=$engine BENCH_TARGET=has_session BENCH_ITERS=2000 \
      ./.venv-3.15/bin/python \
      -m profiling.sampling run --binary -r 10khz \
      -o "$PROFILE_DIR/$engine.bin" \
      ~/work/python/libtmux-protocol/.claude/skills/libtmux-profiler/scripts/bench-libtmux-call.py
  done

$ for engine in subprocess imsg; do
    ./.venv-3.15/bin/python -m profiling.sampling replay \
      "$PROFILE_DIR/$engine.bin" --pstats -o "$PROFILE_DIR/$engine.pstats"
  done

$ ./.venv-3.15/bin/python \
    ~/work/python/libtmux-protocol/.claude/skills/libtmux-profiler/scripts/diff-pstats.py \
    "$PROFILE_DIR/subprocess.pstats" "$PROFILE_DIR/imsg.pstats"
```

**Bench target registry** (in `scripts/bench-libtmux-call.py`):

| `BENCH_TARGET=` | call |
|---|---|
| `has_session` (default) | `server.has_session("bench")` |
| `list_sessions` | `server.sessions` |
| `list_windows` | `session.windows` |
| `session_name` | `session.session_name` |
| `show_options` | `session.cmd("show-options", "-g")` |
| `list_panes` | `session.active_window.panes` |

To add a new target, edit the `BENCH_TARGETS` dict in the script —
the dict is the entire allowlist, so the script can never execute
caller-supplied Python expressions. Higher sample rate (`-r 10khz`)
because each call is sub-millisecond and the 1 kHz default would
miss most of them.

The default socket name embeds `os.getpid()` so back-to-back runs in
a comparison loop don't trip on leftover sessions from a prior run
whose `kill_server` didn't fully drain.

## Known issue — `--diff-flamegraph` is broken in 3.15.0a8

The "natural" one-shot diff workflow (`run --diff-flamegraph baseline.bin`)
crashes in Python 3.15.0a8:

```
File "<...>/python3.15/profiling/sampling/stack_collector.py", line 689,
    in _add_elided_metadata
    if baseline_self > 0:
       ^^^^^^^^^^^^^
UnboundLocalError: cannot access local variable 'baseline_self' where it
    is not associated with a value
```

The samples are captured but the diff HTML never gets written. The
**Quick Recipe above sidesteps this** by capturing two `.bin` files and
replaying them as separate flamegraphs (open side-by-side). When 3.15.x
ships the fix, the one-shot workflow becomes:

```console
$ ... run --diff-flamegraph "$PROFILE_DIR/subprocess.bin" \
    -o "$PROFILE_DIR/diff.html" -m pytest ...   # not yet usable
```

Color legend (when fixed): red=regression, blue=improvement,
gray=no change, purple=new code path.

## Workflow — pstats top-N for terminal-only analysis

When a browser is unavailable or you want a shareable text summary:

```console
$ PROFILE_DIR=$(bash ~/work/python/libtmux-protocol/.claude/skills/libtmux-profiler/scripts/init-profile-session.sh pstats-ad-hoc)
$ SHELL=/bin/sh LIBTMUX_ENGINE=imsg ./.venv-3.15/bin/python \
    -m profiling.sampling run --pstats -r 5khz \
    -o "$PROFILE_DIR/imsg.pstats" \
    -m pytest tests/workspace/test_builder.py --no-cov --engine=imsg -q -p no:randomly
$ ./.venv-3.15/bin/python -c "
import pstats
pstats.Stats('$PROFILE_DIR/imsg.pstats').sort_stats('cumulative').print_stats(30)
"
```

This is what surfaced `_wait_for_pane_ready` and
`subprocess.Popen.communicate → selectors.poll()` as the dominant
wall-time consumers in the original engine-bench investigation.

## Workflow — automated pstats diff (replaces broken `--diff-flamegraph`)

Until 3.15.x ships the `--diff-flamegraph` fix (see *Known issue*
above), use the bundled `diff-pstats.py` helper for structured A/B
comparisons. It loads two `pstats` files, computes per-function
`cumtime` deltas, and prints a markdown table sorted by
`abs(Δ cumtime)` — the biggest movers first, regardless of direction.

```console
$ ./.venv-3.15/bin/python \
    ~/work/python/libtmux-protocol/.claude/skills/libtmux-profiler/scripts/diff-pstats.py \
    "$PROFILE_DIR/subprocess.pstats" "$PROFILE_DIR/imsg.pstats" \
    --top 30
```

Output:

```markdown
# pstats diff (top 30 by |Δ cumtime|)

- baseline: `/tmp/py-profiling/.../subprocess.pstats`
- current:  `/tmp/py-profiling/.../imsg.pstats`

| function | baseline (s) | current (s) | Δ (s) | Δ% |
|---|---:|---:|---:|---:|
| `engines/subprocess.py:53(SubprocessEngine.run)` | 0.688 | 0.000 | -0.688 | -100.0% |
| `subprocess.py:1274(Popen.communicate)` | 0.682 | 0.000 | -0.682 | -100.0% |
| `selectors.py:398(_PollLikeSelector.select)` | 0.652 | 0.000 | -0.652 | -100.0% |
| `engines/imsg/base.py:204(ImsgEngine.run)` | 0.000 | 0.317 | +0.317 | — |
...
```

The markdown is paste-ready for PRs, issues, or chat. **Functions
only present in one profile show "—" in Δ%** (no baseline to compare
against). Sort order is by `abs(Δ)` so a -0.688s drop and a +0.317s
increase both surface near the top.

This is the **primary** comparison tool for the engine A/B recipes
above (Quick Recipe, libtmux-direct, microbenchmark) until upstream
fixes the diff-flamegraph alpha bug.

## Workflow — heatmap for line-level hot spots

Once you've identified a slow function, get exact line-level
attribution. The heatmap renders one HTML page per source file with
color intensity per line.

```console
$ PROFILE_DIR=$(bash ~/work/python/libtmux-protocol/.claude/skills/libtmux-profiler/scripts/init-profile-session.sh heatmap-builder)
$ ./.venv-3.15/bin/python -m profiling.sampling run \
    --heatmap -o "$PROFILE_DIR/heatmap" \
    -m pytest tests/workspace/test_builder.py --no-cov -p no:randomly
```

Open `$PROFILE_DIR/heatmap/index.html` — pick the file you care about.
Add `--opcodes` to see bytecode-level intensity inside hot lines (when
the bottleneck is a Python interpreter detail, not a library call).

## Workflow — live TUI for ad-hoc investigation

`--live` runs a top(1)-style real-time profiler. Useful when a test is
behaving strangely and you want to see the hotspot evolve. Note: live
mode does not write artifacts to disk, so a `PROFILE_DIR` isn't needed.

```console
$ ./.venv-3.15/bin/python -m profiling.sampling run --live \
    -m pytest tests/workspace/test_builder.py::test_automatic_rename_option -v
```

Key shortcuts in the TUI:
- `q` — quit
- `s` / `S` — cycle sort order forward/back
- `p` — pause display (sampling continues)
- `t` — toggle per-thread view
- `/` — filter functions by substring
- `+` / `-` — adjust refresh rate (0.05–1.0s)

## Workflow — attach to a running pytest

When a test is hanging and you want to diagnose without restarting it:

```console
$ pytest tests/workspace/test_builder.py::test_some_hang -v &
$ # note the PID printed by `&`, or get it from `ps`
$ ./.venv-3.15/bin/python -m profiling.sampling attach --live <PID>
```

For a recorded capture instead of live:

```console
$ PROFILE_DIR=$(bash ~/work/python/libtmux-protocol/.claude/skills/libtmux-profiler/scripts/init-profile-session.sh attach-debug)
$ ./.venv-3.15/bin/python -m profiling.sampling attach \
    --binary -d 30 -o "$PROFILE_DIR/attached.bin" <PID>
```

If the target uses `pytest-asyncio`, add `--async-aware` so Tachyon
reconstructs task-level stacks instead of event-loop internals.

## Sampling mode selection — `--mode {wall,cpu,gil,exception}`

| mode | measures | use when |
|---|---|---|
| `wall` (default) | all elapsed time, including I/O / sleep / lock waits | general "where is wall time spent" |
| `cpu` | CPU-active time only | filter out I/O, see compute-bound hotspots |
| `gil` | time holding the Python GIL | multi-threaded contention diagnosis |
| `exception` | time inside `except`/`finally` after a `raise` | exception-driven control flow audits |

For libtmux/tmuxp profiling, `wall` is right ~95% of the time. The
shell-startup wait inside `subprocess.Popen.communicate` and the
explicit poll inside `_wait_for_pane_ready` are *both* I/O-bound and
will be invisible under `cpu` mode.

## Reading the output

**Plain flamegraph**: width = sample count = time. Wide flat plateaus
mean a single function dominates (sleep loops, `selectors.poll`,
fixture setup). Tall narrow spikes mean deep call stacks (often
recursion or framework dispatch chains like pluggy).

**Heatmap**: brighter = more samples on that line. Source-line
attribution is exact; perfect for "I know `fetch_objs` is slow but
which line?" investigations.

**Diff flamegraph** (when 3.15 fixes the alpha bug):
- frame width = current run's time
- color encodes change relative to baseline:
  - **red** = regression (current > baseline; darker = worse)
  - **blue** = improvement (current < baseline; darker = better)
  - **gray** = no meaningful change
  - **purple** = code only in the current run
- hover any frame for `baseline_time / current_time / Δ%`

See `reference/flamegraph-reading.md` for a fuller cheat sheet on
visual signatures.

## Worked example — what we discovered with this exact tooling

**The question**: tmuxp's bench-engines shows subprocess and imsg engines
within ~0.5s of each other on a 30s suite, despite imsg saving 0.6ms per
call across 5300+ calls (theoretical 3s+ delta). Why?

**The investigation** (using the Quick Recipe above on test_builder.py,
57 tests, ~18s wall each engine):

1. **subprocess pstats top** revealed:
   - `subprocess.Popen.communicate` — **5.35s** (29%)
   - `selectors._PollLikeSelector.select` — 5.17s (called from
     `subprocess.py:2293` inside `Popen._communicate`)
   - Kernel `poll()` waiting for tmux child to write to its stdout pipe
   - `_wait_for_pane_ready` — only 4.18s (23%)

2. **imsg pstats top** revealed:
   - `subprocess.Popen.communicate` — **0s** (engine doesn't fork)
   - `selectors.EpollSelector.select` — only 2.17s (just the imsg
     socket I/O wait, not subprocess child wait)
   - **`_wait_for_pane_ready`** (`tmuxp/workspace/builder.py:60-83`) —
     **7.97s** (40%) — explicit Python poll loop waiting for
     `pane.cursor_x` to move from origin

3. **The conclusion**: same shell-readiness wait, accounted differently.
   - subprocess: tmux child blocks until shell writes → `communicate()`
     returns when tmux exits → wait "absorbed" inside the engine call
   - imsg: server returns `MSG_EXIT` in ~2ms (long before shell finishes
     spawning) → tmuxp's builder must explicitly poll → wait "surfaced"
     as visible Python time

The net: imsg saves ~3.0s of `Popen.communicate` poll wait + ~2.3s on
libtmux state queries (`fetch_objs`, `Server.cmd`), but pays ~3.8s
more in `_wait_for_pane_ready` + ~2.3s more in `WorkspaceBuilder.build`
overall. Net wall delta is ~1.5s in either direction depending on the
run's noise.

**Engine choice cannot compress shell startup; it can only choose where
to account for it.** For shell-bound code paths, imsg's
tmux-command-time savings are exactly canceled by the now-explicit
poll loop. For pure libtmux query workloads (no shell waiting), the
imsg savings remain visible.

This kind of insight is the entire reason to keep this skill around:
it would be near-impossible to derive from raw timing alone, but
trivial to spot in side-by-side flamegraphs filtered for the
swap-pair (`Popen.communicate` ↔ `_wait_for_pane_ready`).

## Pitfalls

- **Short scripts (<1s)** don't collect enough samples for reliable
  results. Either loop the target or use `profiling.tracing` (the
  deterministic profiler in 3.15's `profiling.tracing` module).
- **Subprocess children are not profiled by default.** For libtmux's
  subprocess engine, the `tmux` child processes do their own work that
  Tachyon can't see — what you'll see in the flamegraph is the parent
  Python time waiting in `Popen.communicate`. To profile children too,
  add `--subprocesses` (incompatible with `--live`).
- **Sampling rate trade-off.** Default 1 kHz is balanced. For a 30s test
  run, `5khz` (used in the recipes above) gives ~150K samples — plenty
  of resolution. `20khz` adds profiler overhead without meaningful
  detail gain at this duration.
- **Statistical noise.** Numbers vary 1-2% between runs. Don't chase
  small deltas; focus on patterns (which functions dominate? which
  call paths shifted color in the diff?).
- **The `.venv-3.15` venv is separate** from the project's main
  `.venv`. Don't try to use `uv run` with the 3.15 venv unless you've
  set `VIRTUAL_ENV` explicitly — `uv run` uses the project's pinned
  Python (3.14). Always invoke `./.venv-3.15/bin/python ...` directly.
- **`watchfiles` won't build for 3.15a8** (Rust compatibility). The
  bootstrap script installs `--group testing` instead of `dev` to skip
  the docs deps that pull in `sphinx-autobuild` → `watchfiles`.
- **`--diff-flamegraph` UnboundLocalError in 3.15.0a8** — see *Known
  issue* above. Use `--binary` capture + separate `replay` until fixed.

## Output directory layout

Every session lives under:

```
/tmp/py-profiling/
└── <YYYY-MM-DD-HH-MM-SS>/         e.g. 2026-04-28-11-20-25
    └── <project>/                 e.g. tmuxp-libtmux-protocol
        └── <branch>/              e.g. libtmux-protocol  (slashes → underscores)
            └── <session-name>/    e.g. engine-ab
                ├── README.md      session metadata + HEAD sha
                ├── subprocess.bin
                ├── subprocess.html
                ├── subprocess.pstats
                ├── imsg.bin
                ├── imsg.html
                ├── imsg.pstats
                └── heatmap/       (when --heatmap is used)
                    ├── index.html
                    └── *.html
```

The README.md is auto-generated by `init-profile-session.sh` and
captures the git HEAD short-sha, so you can reconstruct the exact code
state even after the branch has moved or been deleted.

Clean up `/tmp/py-profiling/` periodically — pstats files are ~350 KB
each, HTML flamegraphs are 800 KB to a few MB, heatmap directories can
hit 10+ MB.
