# libtmux engine benchmark status

> Status: archived and not current. Do not cite the timings in `grid.json` or
> `wait.json` as evidence for planner batching.

The checked-in raw results predate `BatchingPlanner` and use an earlier workload
whose creation operations could not be batched. They measured transport and tmux
server costs, not the planner optimization their former labels implied. The raw
files remain available only as historical measurements; `STATUS.json` records
that provenance explicitly.

The current benchmark models cardinality as sessions x windows per session x
panes per window. A two-part `WxP` value remains shorthand for one session. Each
multi-session sample builds its sessions sequentially through one engine; the
separate concurrency experiment is not mixed into topology scaling.

The workload adds two adjacent ready session-option operations and checks that
sequential and batching layers emit identical tmux requests with different
planner-step shapes. Its matrix reports these quantities separately:

- planner steps;
- engine batch calls and their request counts;
- distinct tmux requests;
- elapsed build time.

Process-start fields carry their evidence basis. Subprocess command children are
exactly one per request. Control-mode bootstrap children remain unmeasured,
version probes are cache-dependent, and the persistent control client is labeled
as an at-most-one engine model rather than an observed count.

Run the correctness and shape contract before collecting timings:

```console
$ uv run scripts/bench_engines.py contract
```

Run the exhaustive planner matrix on the supported-version-safe pane-heavy
shape. One hundred samples make p90 and p95 useful; treat p99 as descriptive,
not stable evidence:

```console
$ uv run scripts/bench_engines.py matrix \
    --shapes 1x1x4 \
    --runs 100 \
    --json-out scripts/bench-results/matrix.json
```

Run the practical hierarchy corpus through the public default layer:

```console
$ uv run scripts/bench_engines.py matrix \
    --shapes 1x1x1,1x1x4,1x4x1,4x1x1,1x2x2 \
    --layers default \
    --runs 100 \
    --json-out scripts/bench-results/hierarchy.json
```

The script launches every daemon with an empty tmux configuration and verifies
the live session, window, pane, name, and option postconditions outside each
timed interval. A failed operation or partial topology aborts the cell instead
of becoming an artificially fast sample.

Samples within a cell share one warmed daemon and engine. Fixed cell order can
still track machine load or thermal drift, so these results are local
steady-state descriptions rather than independent daemon replicates. Publish a
general speed claim only after collecting seeded, interleaved rounds on an idle
host and retaining environment and round identity with the raw samples.

The `concurrency` subcommand remains exploratory. It lacks an async-sequential
control, symmetric connection-start boundaries, interleaved strategy order, and
event-loop-lag instrumentation. Do not use its ratios as async performance or
asyncio-health evidence.

The hand-written `prototype-pipelined` implementation is opt-in and excluded
from planner parity and default engine runs. It targets objects by chosen names
without the typed plan's captured-id contract, so its timing cannot substantiate
a planner claim.

No current performance conclusion is checked in. Regenerate the matrix on an
idle, controlled host before publishing transport or planner speedups.

## Async control-output demos

The lossless demo scrolls a stable seeded selection of libtmux Python source
through two windows with four panes each. It verifies each pane's decoded bytes,
sequence, source hash, zero-drop delivery, follow-up engine responsiveness, and
cleanup. Increase `--lines` for a longer display:

```console
$ uv run scripts/demo_control_output.py scroll \
    --windows 2 \
    --panes 4 \
    --lines 500 \
    --delay 0.002 \
    --seed 688
```

The overload demo deliberately stalls a one-element subscriber queue. It must
observe dropped notification frames and then prove that the same async engine
still accepts a command. This demonstrates bounded dropping, not producer
backpressure or lossless delivery:

```console
$ uv run scripts/demo_control_output.py overload \
    --windows 2 \
    --panes 4 \
    --lines 2000 \
    --seed 688 \
    --quiet
```
