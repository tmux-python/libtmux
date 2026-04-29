# Engine performance strategies

Workload bench numbers + per-engine pstats, captured 2026-04-29 on
Linux 6.6 / Python 3.14. Reproduce with:

```console
$ BENCH_REPEATS=3 uv run python .claude/skills/libtmux-profiler/scripts/bench-engines-workload.py
```

## Realistic-workload wall time (6-phase build / heavy_q / light_q / mutate / batch / teardown)

| engine         | build   | heavy_q | light_q | mutate | batch  | teardown | TOTAL   |
|----------------|---------|---------|---------|--------|--------|----------|---------|
| `subprocess`   | 103.5ms |  13.0ms | 216.0ms | 23.7ms | 38.5ms |  3.2ms   | 404.6ms |
| `imsg`         |  88.1ms |  10.7ms | 136.3ms | 15.3ms | 32.7ms |  3.6ms   | 288.5ms |
| `control_mode` |  62.0ms |   9.1ms |  21.7ms |  3.0ms | 10.8ms |  0.4ms   | 105.6ms |

Workload composition:

* **build**: 1× `new-session` + 3× `new-window` + 6× `split` (10 mutating cmds)
* **heavy_q**: walk session/window/pane tree, read `name`/`id`/`index` (~14 query cmds)
* **light_q**: 100× `display-message -p ok` (the per-call microbench shape)
* **mutate**: 3× `rename-window`
* **batch**: 10× `new-window` issued via `Server.cmd_batch` in one round-trip
* **teardown**: 1× `kill-server`

Aggregate result: `control_mode` is **3.83× faster than `subprocess`**
and **2.73× faster than `imsg`** on a representative end-to-end
workload. The `batch` phase isolates the pipelining win — `control_mode`
amortises the lock + flush across the whole batch and runs **3.6×
faster than `subprocess`** and **3.0× faster than `imsg`** on the same
10 commands.

## Per-engine hot paths (libtmux-internal frames only)

Profiled with Tachyon at 1 kHz; numbers are sample counts (≈ ms of
wall time). See
`/tmp/py-profiling/2026-04-29-10-25-18/.../workload-isolated/` for
the full pstats files and flamegraphs.

### subprocess (417 ms total)

| samples | frame |
|---------|-------|
| 315/417 (76 %) | `common._run_command` |
| 266 (64 %)     | `engines.subprocess.SubprocessEngine.run` |
| 228 (55 %)     | `server.Server.cmd` |
| 89  (21 %)     | `neo.fetch_objs` (used by listings) |
| 88  (21 %)     | `common.tmux_cmd.__init__` |

Inside `SubprocessEngine.run`, the cost is dominated by
`subprocess.Popen.communicate` → `selectors._PollLikeSelector.select`
(see step-7 microbench pstats: 71 % of engine time waiting for the
child to exit). **The fork + exec + wait cycle is structural** —
not much room to compress without an OS-level change.

### imsg (290 ms total)

| samples | frame |
|---------|-------|
| 182/290 (63 %) | `common._run_command` |
| 159 (55 %)     | `engines.imsg.ImsgEngine.run` |
| 125 (43 %)     | `server.Server.cmd` |
|  53 (18 %)     | `_SelectorSocketTransport.send_frames` |
|  53 (18 %)     | `ImsgEngine._run_socket_command` |
|  51 (18 %)     | `_SelectorSocketTransport.recv_frame` |

The imsg engine pays its cost at the protocol layer: pack frames →
write via SCM_RIGHTS → read frames. This is one fresh AF_UNIX socket
per command. **Persisting the connection is structurally blocked**
by tmux's `MSG_COMMAND` / `MSG_EXIT` exchange, which terminates the
client after each command — see `server-client.c` for the C side.

### control_mode (177 ms total)

| samples | frame |
|---------|-------|
| 77/177 (43 %) | `common._run_command` |
| 54 (31 %)     | `engines.control_mode.base.ControlModeEngine._await_response` |
| 54 (31 %)     | `engines.control_mode.base.ControlModeEngine.run` |
| 46 (26 %)     | `server.Server.cmd` |

`_await_response` is `queue.Queue.get` blocking on the reader
thread's parsed Block — most of those 54 samples are **necessary
wait time** while tmux processes the command, not lock overhead. The
flame is qualitatively different from the other two engines: there's
no structural cost dominating, just synchronisation overhead and the
wrapper layer.

## Cross-engine: the wrapper layer

For `control_mode`, `_run_command` + `Server.cmd` are 43 % + 26 % =
69 % of total wall. **The wrapper layer is engine-agnostic** —
optimising it speeds up all three engines proportionally, with the
biggest visible lift on the engine where engine-internal cost is
already small.

Concrete wins shipped on this branch (`libtmux-protocol-engines`):

* **`Server._svr_prefix` cache** (commits `e55091b5`, `a513e79d`).
  `Server.cmd` used to rebuild the `-L socket_name` / `-S socket_path`
  / `-f config_file` / `-2`/`-8` prefix list on every call via four
  `list.insert(0, …)` operations. Built once at `Server.__init__` and
  reused as a tuple by both `Server.cmd` and `neo.fetch_objs`. Bonus:
  invalid `colors=` values now raise at construction rather than on
  every `cmd()` call (fail-fast).
* **`_run_command` factored out of `tmux_cmd.__init__`** (earlier
  commit `47086007`). Skipped redundant engine dispatch when
  `Server.cmd` already had the resolved engine.
* **`shutil.which("tmux")` memoised per engine instance** (earlier
  commits `7844f6b3`, `47086007`).
* **`get_version()` `lru_cache`d per `tmux_bin`** (PR #662 prereq).

Open items still in the wrapper layer:

* `neo.fetch_objs` is the bulk of query-phase cost. Worth a focused
  follow-up to see if format-string parsing can be cached.
* The `tmux_cmd.__init__` audit is complete: only `get_version()`
  (`common.py:695`, called once per `Server.__init__`) and a
  docstring example construct `tmux_cmd` directly; every hot-path
  call goes through `tmux_cmd.from_result` which uses
  `cls.__new__(cls)` to skip the constructor (commit `12c41266`).
  Remaining samples reflect the unavoidable per-call object
  allocation, not redundant init work.

## Per-engine future strategies

### `subprocess` — limited room

The fork+exec+wait cycle is the floor. Possible micro-wins:

* CPython already uses `os.posix_spawn` for `subprocess.Popen` when
  it can — verify the fast path is taken.
* Reduce `tmux_cmd.__init__` allocations (cross-engine; helps
  subprocess most because subprocess has the most calls/sec).

Realistic ceiling: 5–10 % via wrapper-layer wins. The structural
cost is what it is.

### `imsg` — structurally blocked from connection reuse

tmux's `MSG_COMMAND` / `MSG_EXIT` exchange forces a fresh client
connection per command. Making imsg "persistent" would require
adopting the control-mode protocol — at which point it would be
control_mode (which we already have). Possible micro-wins:

* Cache the protocol codec instance on the engine (already memoised
  per call site; verify per-engine reuse).
* Use `os.posix_spawnp` directly for the `tmux` binary spawn during
  bootstrap to skip Python's `subprocess.Popen` overhead (small
  one-time saving).

Realistic ceiling: 10 % via micro-wins; significantly more is a
protocol redesign.

### `control_mode` — pipelining is shipped

**Shipped on this branch:** `engine.run_batch(requests)` and
`Server.cmd_batch(commands)` issue N command lines in one
`stdin.write` + `flush`, then drain N `Block` events from the
response queue in order. tmux's command parser FIFOs the lines via
`cmd-queue.c:315`, so the i-th block is the i-th request's response.
Lock + flush amortise once across the whole batch instead of once per
call.

**Worked example:**

```python
import libtmux
server = libtmux.Server(socket_name="dev", engine="control_mode")
server.new_session(session_name="primary")

# Create 10 windows in one round-trip:
results = server.cmd_batch(
    [("new-window", "-d", "-n", f"w{i}") for i in range(10)],
)
assert all(r.returncode == 0 for r in results)
```

**Wire path** (verified from the `_send_batch` helper):

* The combined `b"new-window -d -n w0\nnew-window -d -n w1\n..."`
  hits the kernel pipe in one `write(2)` syscall.
* tmux's `evbuffer_readln` (`control.c:557`) splits on `\n` and
  appends each command to its queue.
* The reader thread receives N `%begin`/`%end` blocks, parser emits
  N `Block` events in order, all routed to the response queue
  before `cmd_batch` starts draining.

**Measured wins** on this branch's workload bench (3 repeats,
median, 10-window cmd_batch):

| engine         | batch (10 windows) | per command |
|----------------|--------------------|-------------|
| `subprocess`   | 41.6 ms            | 4.16 ms     |
| `imsg`         | 35.4 ms            | 3.54 ms     |
| `control_mode` | **9.9 ms**         | **0.99 ms** |

`control_mode` batched is **4.2× faster than `subprocess`** and
**3.6× faster than `imsg`** per command on the pipelined path.
Subprocess and imsg run `[self.run(req) for req in requests]` so
they pay the same per-call cost as a single call — the API is
uniform, the speedup is engine-specific.

**Caveats:**

* `attach-session` mid-batch falls through to the subprocess engine
  (per `_engine_for_command`), which forces `Server.cmd_batch` onto
  the slow per-command path. Keep batches engine-uniform.
* The whole batch happens under one lock acquire, so concurrent
  `run()` from another thread blocks until the batch finishes.
  Same serialisation contract as today.
* Engine-broken errors (broken pipe / EOF mid-batch) raise
  `TmuxControlModeError` — partial results are not returned because
  the connection is gone. Per-command tmux `%error` *does* surface
  as `returncode=1` per result.

**Also shipped on this branch:**

* **`threading.Event` + result slot** (commit `3cf7f9aa`) replaces
  the per-call `queue.Queue.get` with a single-event wait keyed on a
  `_PendingSlot` that the reader thread fills directly. Trims the
  per-call lock count from 2–3 (queue mutex + not-empty condvar) to
  1 (the event's internal lock). Visible at the microsecond scale —
  the workload bench `light_q` shifted from 24.0ms to 21.7ms
  post-refactor.
* **`Server.batch()` accumulator context manager** (commit
  `b320213b`) for runtime-built command lists:

  ```python
  with server.batch() as b:
      for name in window_names_from_config:
          b.cmd("new-window", "-d", "-n", name)
      results = b.results()
  ```

  Layers over `cmd_batch` — same pipelining contract, fluent API.
* **Mixed-engine batch auto-partitioning** (commit `550accab`):
  `Server.cmd_batch` detects per-command engine routing internally
  and splits the input into engine-uniform contiguous runs, calling
  `run_batch` on each. A 5-command batch
  `[a, b, attach-session, c, d]` becomes
  `run_batch([a, b])` + `run([attach-session])` + `run_batch([c, d])`,
  preserving pipelining for the surrounding commands while honouring
  the carve-out for `attach-session`.
* **tmuxp `WorkspaceBuilder` consumes the API** (tmuxp commits
  `d133ce68` + `11a3c830`): the four metadata `set-option` loops
  (session `options`, `global_options`, window `options`,
  `options_after`) now route through `Server.batch()`. On
  `control_mode`, an options-heavy workspace collapses N round-trips
  into one batched flush per loop. Out of libtmux's tree but the
  user-visible payoff for the engine work.

## When to use which engine

* **`subprocess`** — default. Maximum compatibility. Use unless you
  are sure your workload is dominated by libtmux call overhead.
* **`imsg`** — slightly faster than `subprocess`, no fork. Good for
  environments where `fork` is heavy (containers, sandboxes,
  WSL2). Same per-call overhead shape; marginal aggregate
  improvement.
* **`control_mode`** — best per-call cost; the only engine that
  supports `Server.subscribe` real-time format updates. Use when:
  the workload issues many libtmux calls in a single Python
  process, or when you need real-time tmux-side state pushes.
