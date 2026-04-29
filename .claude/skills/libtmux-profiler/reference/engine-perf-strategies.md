# Engine performance strategies

Workload bench numbers + per-engine pstats, captured 2026-04-29 on
Linux 6.6 / Python 3.14. Reproduce with:

```console
$ BENCH_REPEATS=3 uv run python .claude/skills/libtmux-profiler/scripts/bench-engines-workload.py
```

## Realistic-workload wall time (6-phase build / heavy_q / light_q / mutate / batch / teardown)

| engine         | build   | heavy_q | light_q | mutate | batch  | teardown | TOTAL   |
|----------------|---------|---------|---------|--------|--------|----------|---------|
| `subprocess`   | 106.7ms |  13.3ms | 221.1ms | 25.1ms | 42.0ms |  3.9ms   | 414.0ms |
| `imsg`         |  83.5ms |   9.4ms | 120.7ms | 11.5ms | 25.5ms |  3.8ms   | 256.6ms |
| `control_mode` |  58.1ms |   8.4ms |  25.6ms |  3.0ms |  9.5ms |  0.6ms   | 103.0ms |

Workload composition:

* **build**: 1× `new-session` + 3× `new-window` + 6× `split` (10 mutating cmds)
* **heavy_q**: walk session/window/pane tree, read `name`/`id`/`index` (~14 query cmds)
* **light_q**: 100× `display-message -p ok` (the per-call microbench shape)
* **mutate**: 3× `rename-window`
* **batch**: 10× `new-window` issued via `Server.cmd_batch` in one round-trip
* **teardown**: 1× `kill-server`

Aggregate result: `control_mode` is **4.0× faster than `subprocess`**
and **2.5× faster than `imsg`** on a representative end-to-end
workload. The `batch` phase isolates the pipelining win — `control_mode`
amortises the lock + flush across the whole batch and runs **4.4×
faster than `subprocess`** and **2.7× faster than `imsg`** on the same
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

### control_mode (1.43 s total on `tests/test_server.py --engine=control_mode`)

Profiled at 5 kHz on the 47-fixture suite (200 µs per sample);
libtmux-internal frames only:

| samples × 200µs | frame |
|---------|-------|
| 727 ms (51 %) | `common._run_command` |
| 681 ms (48 %) | `server.Server.cmd` |
| 538 ms (38 %) | `engines.control_mode.base.ControlModeEngine._await_response` |
| 532 ms (37 %) | `engines.control_mode.base.ControlModeEngine.run` |
|  53 ms (4 %)  | `engines.control_mode.base.ControlModeEngine._ensure_started` |

The bulk of `_await_response` is **necessary wait time** while
tmux processes the command, not lock overhead. The
synchronous startup-ACK wait that previously dominated this profile
(`_drain_startup_ack` was 41 % of wall on the same suite, ~700 ms
cumulative across 47 fresh engines) is gone — see *Pipelined
startup ACK* below.

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

Try-then-handle wins shipped (the same general pattern as imsg's
optimistic IO and control_mode's pipelined startup ACK):

* **`Server.new_session` drops `has-session` pre-check** (commit
  `c692941c`). Instead of probing for a name conflict before
  creating, we issue the new-session command and parse tmux's
  stable ``"duplicate session: %s"`` stderr (per
  ``cmd-new-session.c:128``) when the name collides. Saves one
  round-trip per call in the no-conflict case (the common case in
  fixtures and user code). Apples-to-apples bench (3 trials each,
  ``pytest tests/test_session.py --engine=<X>``):

  | engine       | baseline | post-fix | Δ |
  |--------------|----------|----------|---|
  | subprocess   |  1.12 s  |  1.05 s  | **−6.3 %** |
  | imsg         |  0.77 s  |  0.77 s  |   ±0 % (round-trip too cheap) |
  | control_mode |  0.68 s  |  0.65 s  |  −4.4 % |

  Engine-uniform wrapper-layer win, surfacing in proportion to
  per-round-trip cost. The conflict path (`kill_session=True` or
  ``TmuxSessionExists`` on collision) is observably unchanged —
  same exception type, same kill-then-retry flow when requested.

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
control_mode (which we already have).

**Shipped on this branch:**

* **Optimistic non-blocking IO** (commit `a265ccdf`).
  `_send_all` / `_send_frame_with_fd` / `_recv_more` flipped from
  "wait, then act" to "act, on `BlockingIOError` wait", matching
  the pattern asyncio's transports use internally. The pre-IO
  `selector.modify` + `epoll_wait` was paying its full cost for
  almost zero blocking — imsg fragments each command into ~100
  small frames, and a fresh AF_UNIX SOCK_STREAM never has its send
  buffer full at first send. Apples-to-apples bench (5 repeats):
  imsg total **287.8 ms → 256.6 ms (−10.8 %)**, with the
  per-call-overhead-dominated `light_q` phase improving 16.5 %.
  See the commit message for the full per-phase breakdown.

Possible further micro-wins:

* Cache the protocol codec instance on the engine (already memoised
  per call site; verify per-engine reuse).
* Use `os.posix_spawnp` directly for the `tmux` binary spawn during
  bootstrap to skip Python's `subprocess.Popen` overhead (small
  one-time saving).

Realistic ceiling at this point: <5 % via additional micro-wins.
Significantly more is a protocol redesign.

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
* **Pipelined startup ACK** (commit `a68291ab`). The synchronous
  `_drain_startup_ack` round-trip that bracketed every fresh
  `ControlModeEngine` is gone — the reader thread auto-discards
  tmux's cfg-load `%begin`/`%end` block (`flags=0` per
  `cmd-queue.c:618`) the first time it sees one, and the user's
  first command pipelines its `stdin.write` with config-load.
  The kernel pipe buffer absorbs the command write while tmux is
  still initialising; tmux processes commands in arrival order and
  emits responses after the ACK, so the reader's FIFO routing
  delivers the response correctly to the user's slot.

  **Where the win shows up:** short-lived-engine workloads (test
  suites, CLI invocations, anything that creates a fresh
  `ControlModeEngine` per logical operation). Tachyon profile of
  `tests/test_server.py --engine=control_mode` (47 fixtures,
  5 kHz):

  | metric | before | after | Δ |
  |---|---|---|---|
  | total wall | 1.71 s | 1.43 s | **−16 %** |
  | `_drain_startup_ack` cumulative | 713 ms | (deleted) | — |
  | `_ensure_started` cumulative | 707 ms | 53 ms | **−92 %** |

  Workload bench (one engine, many commands) is unchanged — the
  startup amortises across the run.

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
