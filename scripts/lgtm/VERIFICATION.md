# What has been verified, and how

This records what was exercised and by which command, so a claim here can be
re-run rather than taken on trust. Every row was executed against a live stack
and a real tmux server.

Reproduce the whole thing with one command:

```console
$ just otel-verify
```

## Permutation matrix

### Transport against signal

One smoke run drives all four transports; each cell was queried from its own
backend afterwards. **16/16 populated.**

| transport | metrics | traces | logs | profiles |
| --------- | ------- | ------ | ---- | -------- |
| `subprocess` | yes | yes | yes | yes |
| `control` | yes | yes | yes | yes |
| `subprocess-async` | yes | yes | yes | yes |
| `control-async` | yes | yes | yes | yes |

Profiles are per transport because the CPU sampler is tagged per lane.
Allocation profiles are per run; see below.

### tmux versions

Both transports plus the notification stream, against every build. Identical
command and inlining counts on all of them, no dropped notifications.
**8/8 exercised.**

| 3.2a | 3.3a | 3.4 | 3.5 | 3.6 | 3.7 | 3.7a | 3.7b |
| ---- | ---- | --- | --- | --- | --- | ---- | ---- |
| yes | yes | yes | yes | yes | yes | yes | yes |

### Load shapes

`just otel-load`, two transports against two executors. **4/4, no check
failures.**

| | `steady` (constant VUs) | `ramp` (ramping arrival rate) |
| --- | --- | --- |
| `control-async` | yes | yes |
| `subprocess-async` | yes | yes |

### Profile types

| type | collected | scope |
| ---- | --------- | ----- |
| `process_cpu:cpu:nanoseconds` | always | per transport |
| `memory:alloc_space:bytes` | `--memory-profile` | per run |
| `memory:alloc_objects:count` | `--memory-profile` | per run |
| `memory:inuse_space:bytes` | `--memory-profile` | per run |

The goroutine, mutex, and block types Pyroscope advertises belong to Go
runtimes and stay empty for a Python process.

### Identity resolution

| case | result |
| ---- | ------ |
| branch checkout | branch name, type `branch` |
| detached HEAD | short revision, type `revision`, never the literal `HEAD` |
| detached at a tag | tag name, type `tag` |
| `LIBTMUX_VCS_REF` set | the override wins over the checkout |
| outside a repository | no `vcs.*` attributes, no error |

### Failure paths

Each fails loudly and names the next action.

| case | behaviour |
| ---- | --------- |
| stack not running | acceptance exits in ~18s, prints `just otel-up` |
| port shadowed by a host service | `up.sh` refuses, prints the override variable |
| dashboards edited by hand | test fails, prints `just otel-dashboards` |
| unknown load transport | exits in ~3s, lists the valid ones |

## Dimension scorecard

Each rating is backed by something executed, not an opinion.

| dimension | evidence |
| --------- | -------- |
| Dashboards | 43/43 panel queries return data, checked against the panels' own JSON |
| Examples | 64 doctested examples; every console block in this directory was run as written |
| Docs | tests fail if the README shows a recipe that does not exist, or omits a generated board |
| Scannability | one command to a verified stack; 9/9 tasks carry descriptions |
| MCP | Tempo's 7 tools reached over a real handshake; `just otel-mcp` emits a config with this stack's ports, token never committed |
| async | concurrent scopes attribute correctly; overlapping tasks preserved under load |
| control mode | both transports on 8 tmux builds |
| streaming | 240 notifications consumed in a 3s lane, none dropped, commands unaffected |
| asyncio correctness | full run under `PYTHONASYNCIODEBUG=1`: no slow callbacks, un-awaited coroutines, or un-retrieved task exceptions |
| benchmarking | open-model load finds saturation the fixed-worker loop hides: p99 about 2ms steady against about 16ms at the top of a ramp |
| profiling | CPU profile filterable per transport; a bogus transport returns nothing, so the filter is real |

## Deliberately not covered

Allocation profiles are not per transport. The lane tag scopes the CPU
sampler and the allocation profiler does not consult it, so claiming otherwise
would be wrong.

Streaming counters are per-run scalars rather than per-notification, so they
answer "did this run drop anything" and not "when". A rate would cost a metric
record per notification, which is real overhead on a hot stream.

Cross-repository telemetry has nothing to permute yet: the other libtmux ports
have no instrumentation seam, so adding one is separate work rather than a
test.
