---
name: libtmux-profiler
description: Use when the user wants to profile or benchmark libtmux/tmuxp performance — investigating "where is the lag", "why is the test suite slow", flamegraphs, heatmaps, hot-spot analysis, or pstats diffs. TRIGGER when phrases include "profile libtmux", "profile tmuxp", "tachyon", "flamegraph", "heatmap", "where is the bottleneck", "where is the lag", "benchmark libtmux", "benchmark tmuxp", "how fast is", "microbench", "single-call speed", "per-call timing", or "diff pstats". Uses Python 3.15's stdlib profiling.sampling module (Tachyon) plus a pstats-arithmetic diff helper for structured comparisons. SKIP for unrelated profiling questions.
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
   `~/work/python/libtmux/.tool-versions` declares it for this repo.

2. **A `.venv-3.15` venv** in the target repo with libtmux/tmuxp installed
   editable. If missing, run the bootstrap script:
   ```console
   $ bash ~/work/python/libtmux/.claude/skills/libtmux-profiler/scripts/setup-tachyon-venv.sh
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
$ PROFILE_DIR=$(bash ~/work/python/libtmux/.claude/skills/libtmux-profiler/scripts/init-profile-session.sh slow-suite)
$ echo "$PROFILE_DIR"
/tmp/py-profiling/2026-04-28-11-20-25/libtmux/main/slow-suite/
```

**Always `cd` into the target repo first** — the script reads
`git rev-parse --show-toplevel` from `$PWD`, so the project name and branch
are auto-detected.

## Which recipe should I use?

| if the question is... | use |
|---|---|
| "where is wall time spent in this test suite?" | **Workflow — pstats top-N** |
| "structured comparison of two profiles (before/after a change)" | **Workflow — automated pstats diff** |
| "what hot lines in this function?" | **Workflow — heatmap** |
| "test is hanging, what's it doing?" | **Workflow — live TUI / attach** |
| "how fast is `server.X()`?" | **Recipe — single-call microbenchmark** |

The Workflows are general-purpose; the single-call microbenchmark
recipe is for measuring per-call cost of one libtmux API in isolation
without any test framework overhead.

## Workflow — pstats top-N for terminal-only analysis

When a browser is unavailable or you want a shareable text summary:

```console
$ PROFILE_DIR=$(bash ~/work/python/libtmux/.claude/skills/libtmux-profiler/scripts/init-profile-session.sh pstats-ad-hoc)
$ SHELL=/bin/sh ./.venv-3.15/bin/python \
    -m profiling.sampling run --pstats -r 5khz \
    -o "$PROFILE_DIR/suite.pstats" \
    -m pytest tests/test_server.py --no-cov -q -p no:randomly
$ ./.venv-3.15/bin/python -c "
import pstats
pstats.Stats('$PROFILE_DIR/suite.pstats').sort_stats('cumulative').print_stats(30)
"
```

This is the single most useful recipe: it surfaces the dominant
wall-time consumers (e.g. `subprocess.Popen.communicate`,
`selectors.poll()`, fixture setup) in seconds without needing a
browser. Use it as the first step before deciding whether deeper
investigation (flamegraph, heatmap) is worth it.

**Why `SHELL=/bin/sh`:** aligns the runtime env with the test config
(`default-shell /bin/sh` set in libtmux's pytest plugin) so any
`os.getenv("SHELL")`-reading code paths agree with what tmux actually
spawns.

**Why `-p no:randomly`:** ensures repeatable test order so before/after
profiles compare apples to apples.

## Workflow — automated pstats diff (structured before/after)

For "did my optimization actually help?" or "what regressed since
master?" comparisons. Use the bundled `diff-pstats.py` helper: it
loads two `pstats` files, computes per-function `cumtime` deltas, and
prints a markdown table sorted by `abs(Δ cumtime)` — the biggest
movers first, regardless of direction.

The recommended workflow is to capture two `.bin` binaries (Tachyon's
fast capture format), replay each into a `.pstats`, and run
`diff-pstats.py`:

```console
$ cd ~/work/python/libtmux
$ PROFILE_DIR=$(bash ~/work/python/libtmux/.claude/skills/libtmux-profiler/scripts/init-profile-session.sh before-after)

# Capture baseline (e.g. on master).
$ git checkout master
$ SHELL=/bin/sh ./.venv-3.15/bin/python \
    -m profiling.sampling run --binary -r 5khz \
    -o "$PROFILE_DIR/baseline.bin" \
    -m pytest tests/test_server.py --no-cov -p no:randomly

# Capture current (e.g. on your branch).
$ git checkout your-branch
$ SHELL=/bin/sh ./.venv-3.15/bin/python \
    -m profiling.sampling run --binary -r 5khz \
    -o "$PROFILE_DIR/current.bin" \
    -m pytest tests/test_server.py --no-cov -p no:randomly

# Replay each binary to pstats.
$ for tag in baseline current; do
    ./.venv-3.15/bin/python -m profiling.sampling replay \
      "$PROFILE_DIR/$tag.bin" --pstats -o "$PROFILE_DIR/$tag.pstats"
  done

# Markdown diff table.
$ ./.venv-3.15/bin/python \
    ~/work/python/libtmux/.claude/skills/libtmux-profiler/scripts/diff-pstats.py \
    "$PROFILE_DIR/baseline.pstats" "$PROFILE_DIR/current.pstats" \
    --top 30
```

Output:

```markdown
# pstats diff (top 30 by |Δ cumtime|)

- baseline: `/tmp/py-profiling/.../baseline.pstats`
- current:  `/tmp/py-profiling/.../current.pstats`

| function | baseline (s) | current (s) | Δ (s) | Δ% |
|---|---:|---:|---:|---:|
| `common.py:320(get_version)` | 1.234 | 0.012 | -1.222 | -99.0% |
| `subprocess.py:1274(Popen.communicate)` | 5.350 | 4.100 | -1.250 | -23.4% |
| ... |
```

The markdown is paste-ready for PRs, issues, or chat. **Functions
only present in one profile show "—" in Δ%** (no baseline to compare
against). Sort order is by `abs(Δ)` so a -1.222s drop and a +0.317s
increase both surface near the top.

## Recipe — single-call microbenchmark

For "how fast is `server.has_session()`?"-shaped questions. Skips the
test framework entirely and runs a tight loop against a real tmux
server using a pre-defined registry of bench targets.

```console
$ cd ~/work/python/libtmux
$ PROFILE_DIR=$(bash ~/work/python/libtmux/.claude/skills/libtmux-profiler/scripts/init-profile-session.sh microbench-has-session)

$ SHELL=/bin/sh BENCH_TARGET=has_session BENCH_ITERS=2000 \
    ./.venv-3.15/bin/python \
    -m profiling.sampling run --binary -r 10khz \
    -o "$PROFILE_DIR/run.bin" \
    ~/work/python/libtmux/.claude/skills/libtmux-profiler/scripts/bench-libtmux-call.py

$ ./.venv-3.15/bin/python -m profiling.sampling replay \
    "$PROFILE_DIR/run.bin" --pstats -o "$PROFILE_DIR/run.pstats"

$ ./.venv-3.15/bin/python -c "
import pstats
pstats.Stats('$PROFILE_DIR/run.pstats').sort_stats('cumulative').print_stats(30)
"
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

## Workflow — heatmap for line-level hot spots

Once you've identified a slow function, get exact line-level
attribution. The heatmap renders one HTML page per source file with
color intensity per line.

```console
$ PROFILE_DIR=$(bash ~/work/python/libtmux/.claude/skills/libtmux-profiler/scripts/init-profile-session.sh heatmap-server)
$ ./.venv-3.15/bin/python -m profiling.sampling run \
    --heatmap -o "$PROFILE_DIR/heatmap" \
    -m pytest tests/test_server.py --no-cov -p no:randomly
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
    -m pytest tests/test_server.py::test_no_server_is_alive -v
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
$ pytest tests/test_server.py::test_some_hang -v &
$ # note the PID printed by `&`, or get it from `ps`
$ ./.venv-3.15/bin/python -m profiling.sampling attach --live <PID>
```

For a recorded capture instead of live:

```console
$ PROFILE_DIR=$(bash ~/work/python/libtmux/.claude/skills/libtmux-profiler/scripts/init-profile-session.sh attach-debug)
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
shell-startup wait inside `subprocess.Popen.communicate` and any
explicit poll loops are *both* I/O-bound and will be invisible under
`cpu` mode.

## Reading the output

**Plain flamegraph**: width = sample count = time. Wide flat plateaus
mean a single function dominates (sleep loops, `selectors.poll`,
fixture setup). Tall narrow spikes mean deep call stacks (often
recursion or framework dispatch chains like pluggy).

**Heatmap**: brighter = more samples on that line. Source-line
attribution is exact; perfect for "I know `fetch_objs` is slow but
which line?" investigations.

See `reference/flamegraph-reading.md` for a fuller cheat sheet on
visual signatures.

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

The samples are captured but the diff HTML never gets written. **The
*automated pstats diff* workflow above sidesteps this** with the
bundled `diff-pstats.py` helper that operates on `.pstats` files
instead of `.bin` files. When 3.15.x ships the fix, the one-shot
workflow becomes:

```console
$ ... run --diff-flamegraph "$PROFILE_DIR/baseline.bin" \
    -o "$PROFILE_DIR/diff.html" -m pytest ...   # not yet usable
```

Color legend (when fixed): red=regression, blue=improvement,
gray=no change, purple=new code path.

## Pitfalls

- **Short scripts (<1s)** don't collect enough samples for reliable
  results. Either loop the target or use `profiling.tracing` (the
  deterministic profiler in 3.15's `profiling.tracing` module).
- **Subprocess children are not profiled by default.** libtmux shells
  out to `tmux` via `subprocess.Popen`; the `tmux` child does its own
  work that Tachyon can't see — what you'll see in the flamegraph is
  the parent Python time waiting in `Popen.communicate`. To profile
  children too, add `--subprocesses` (incompatible with `--live`).
- **Sampling rate trade-off.** Default 1 kHz is balanced. For a 30s test
  run, `5khz` (used in the recipes above) gives ~150K samples — plenty
  of resolution. `20khz` adds profiler overhead without meaningful
  detail gain at this duration.
- **Statistical noise.** Numbers vary 1-2% between runs. Don't chase
  small deltas; focus on patterns (which functions dominate? which
  call paths shifted in the diff?).
- **The `.venv-3.15` venv is separate** from the project's main
  `.venv`. Don't try to use `uv run` with the 3.15 venv unless you've
  set `VIRTUAL_ENV` explicitly — `uv run` uses the project's pinned
  Python (3.14). Always invoke `./.venv-3.15/bin/python ...` directly.
- **`watchfiles` won't build for 3.15a8** (Rust compatibility). The
  bootstrap script installs `--group testing` instead of `dev` to skip
  the docs deps that pull in `sphinx-autobuild` → `watchfiles`.
- **`--diff-flamegraph` UnboundLocalError in 3.15.0a8** — see *Known
  issue* above. Use the `diff-pstats.py` helper until fixed.

## Output directory layout

Every session lives under:

```
/tmp/py-profiling/
└── <YYYY-MM-DD-HH-MM-SS>/         e.g. 2026-04-28-11-20-25
    └── <project>/                 e.g. libtmux
        └── <branch>/              e.g. main  (slashes → underscores)
            └── <session-name>/    e.g. before-after
                ├── README.md      session metadata + HEAD sha
                ├── baseline.bin
                ├── baseline.pstats
                ├── current.bin
                ├── current.pstats
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
