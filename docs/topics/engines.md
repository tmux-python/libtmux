(engines)=
# Engines

libtmux executes every tmux command through an *engine* — a thin
abstraction over the wire protocol used to talk to the tmux server.
Three engines ship today and you can swap between them per-Server,
per-process (via the `LIBTMUX_ENGINE` environment variable), or
process-wide (via {func}`libtmux.common.set_default_engine`).

## Choosing an engine

| Engine         | When to use                                                                |
|----------------|----------------------------------------------------------------------------|
| `subprocess`   | Default. Maximum compatibility — works against every tmux without setup.   |
| `imsg`         | Slightly faster than `subprocess` (~25 %), no fork. No persistent state.   |
| `control_mode` | Best per-call performance and the only engine that supports subscriptions. |

Selecting per Server:

```python
import libtmux

server = libtmux.Server(socket_name="dev", engine="control_mode")
session = server.new_session(session_name="primary")
```

Selecting via environment variable (overrides the built-in default,
loses to explicit `engine=` arguments):

```console
$ LIBTMUX_ENGINE=control_mode uv run python my_script.py
```

Process-wide programmatic default:

```python
from libtmux.common import set_default_engine
from libtmux.engines.control_mode import ControlModeEngine

set_default_engine(ControlModeEngine())
```

Resolution precedence: `Server(engine=…)` > `set_default_engine()`
> `LIBTMUX_ENGINE` env > `subprocess` (built-in default).

## Performance

Microbench against a pre-spawned tmux server, 200 iterations of
`display-message -p ok` (Linux 6.6, Python 3.14):

| Engine         | avg     | p50     | p99     |
|----------------|---------|---------|---------|
| `subprocess`   | 1.56 ms | 1.50 ms | 2.44 ms |
| `imsg`         | 1.18 ms | 1.12 ms | 2.30 ms |
| `control_mode` | 0.20 ms | 0.17 ms | 0.50 ms |

`control_mode` wins because every call is just one stdin write plus a
parser dispatch — there is no per-call connection setup. The other
two engines re-pay process or socket setup on every command.

Reproduce the numbers locally:

```console
$ python .claude/skills/libtmux-profiler/scripts/bench-engines-ab.py
```

## Batch dispatch (`Server.cmd_batch`)

For workloads that issue many tmux commands in a row — creating N
windows, renaming N sessions, querying N panes — `Server.cmd_batch`
amortises per-call overhead. Each entry in the input is the same
shape as one set of arguments to {meth}`Server.cmd`:

```python
import libtmux

server = libtmux.Server(socket_name="dev", engine="control_mode")
server.new_session(session_name="primary")

results = server.cmd_batch(
    [
        ("new-window", "-d", "-n", "build"),
        ("new-window", "-d", "-n", "test"),
        ("new-window", "-d", "-n", "logs"),
    ],
)
for result in results:
    assert result.returncode == 0
```

The win is engine-specific:

* On **`control_mode`**, all N command lines go out in one
  `stdin.write` + flush; the lock is acquired once across the whole
  batch; tmux's command queue (`cmd-queue.c:315`) processes the lines
  FIFO and emits N `%begin`/`%end` blocks in send order. **~4×
  speedup over single-call `Server.cmd` loops** on a 10-window batch
  (see the bench numbers in
  `.claude/skills/libtmux-profiler/reference/engine-perf-strategies.md`).
* On **`subprocess`** and **`imsg`**, `cmd_batch` is a trivial loop
  over `cmd()` — same per-call cost, uniform API. Useful for code
  that wants to support engine-agnostic batch shapes.

Per-result error semantics match {meth}`Server.cmd`: a tmux-side
`%error` becomes `returncode=1` plus populated `stderr` — never an
exception. Engine-broken errors (broken pipe / EOF on
`control_mode`) raise as they do for single calls.

`cmd_batch` keeps the {meth}`Server._engine_for_command` carve-out
per command — an `attach-session` mid-batch falls through to the
subprocess engine. The batch then auto-partitions into engine-uniform
contiguous runs and dispatches each via that engine's `run_batch`,
preserving pipelining for the surrounding commands. A 5-command
batch `[a, b, attach-session, c, d]` becomes
`run_batch([a, b])` + `run([attach-session])` + `run_batch([c, d])`
under the hood.

### Accumulator pattern (`Server.batch()`)

When the command list is built incrementally — inside a loop, or
branching on earlier results — use the {meth}`Server.batch` context
manager instead of constructing a list up-front:

```python
with server.batch() as b:
    for name in window_names_from_config:
        b.cmd("new-window", "-d", "-n", name)
    if attach_back:
        b.cmd("select-window", "-t", "0")
    results = b.results()
```

`b.cmd(cmd, *args)` accumulates; `b.results()` flushes via
`cmd_batch` and returns the ordered `tmux_cmd` list. `results()` is
idempotent — calling it twice returns the same list. Adding to the
batch after `results()` raises. The context manager does **not**
auto-flush on exit: forgetting to call `results()` is a programming
error worth surfacing as a no-op rather than masking with implicit
dispatch.

## Subscriptions (`control_mode` only)

The control-mode engine surfaces tmux's `refresh-client -B` mechanism
as a sync, queue-based subscription API. Format values are pushed to
the subscriber whenever they change server-side — no polling.

```python
import libtmux

server = libtmux.Server(socket_name="dev", engine="control_mode")
server.new_session(session_name="primary")

sub = server.subscribe(
    name="active-pane-pwd",
    fmt="#{pane_pwd}",
    target="%*",  # all panes; or "%<id>", "@<id>", "@*", None
)

# Drain values as they arrive. tmux only emits when the value changes,
# so the queue receives one entry per actual change — not one per poll.
new_pwd = sub.queue.get(timeout=1.0)

# When done:
sub.unsubscribe()
```

The queue is bounded (default `maxsize=128`) with drop-oldest
semantics so the engine's reader thread never blocks on a slow
consumer. Names cannot contain `:` because tmux's own parser splits
the `-B` argument on colons (`name:target:fmt`).

`Server.subscribe` raises `LibTmuxException` on the `subprocess` and
`imsg` engines — those engines have no persistent connection on
which notifications could arrive.

## Engine choice and `attach-session`

`attach-session` is hard-routed through the subprocess engine on
every Server, regardless of the user's choice. The reason is
semantic: `attach-session` promotes a tmux client into a persistent
*attached* session, which neither `imsg`'s one-shot
`MSG_COMMAND` → `MSG_EXIT` loop nor `control_mode`'s headless control
client can host. Every other tmux command — including
`switch-client`, `kill-session`, and the read-only listings — flows
through the engine you selected.

## Lifecycle

`subprocess` and `imsg` are stateless — there is nothing to clean up
between calls. `control_mode` keeps a long-lived subprocess and a
reader thread; tear them down via:

```python
server.engine.close()  # only when engine is ControlModeEngine
```

If you forget, a {func}`weakref.finalize` registered when the
subprocess spawns will reap the child + reader thread when the engine
is garbage-collected. The recommended explicit path uses tmux's
documented empty-line `CLIENT_EXIT` signal first, escalates through
stdin-EOF, `SIGTERM`, then `SIGKILL`.
