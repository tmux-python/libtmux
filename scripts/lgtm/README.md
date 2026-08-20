# Local observability stack

A single container running Grafana, Loki, Tempo, Prometheus, Pyroscope, and an
OpenTelemetry collector, plus the libtmux dashboards that read from it. It
exists to answer what a tmux workload actually costs: how many commands each
transport issues, how long they take, which ones tmux rejects, and where Python
spent its time getting there.

Nothing here is imported by libtmux. Telemetry is emitted through the engine
instrumentation seam, so the exporters are ordinary sinks and the engines are
untouched. See [`docs/experimental/instrumentation.md`](../../docs/experimental/instrumentation.md)
for the seam itself.

## Run the whole thing

Start the stack, drive a real tmux workload through it, and verify every
dashboard panel returns data:

```console
$ just otel-verify
```

That is the command to reach for first. The steps below are the same workflow
taken one piece at a time.

Start or restart the stack:

```console
$ just otel-up
```

Drive a workload:

```console
$ just otel-smoke
```

Drive a ramping arrival rate instead, to find where a transport saturates:

```console
$ just otel-load
```

Check that every panel has data:

```console
$ just otel-acceptance
```

Stop it:

```console
$ just otel-down
```

## Ports

| Service | URL | |
| ------- | --- | --- |
| Grafana | <http://127.0.0.1:3900> | `admin` / `admin` |
| Prometheus | <http://127.0.0.1:9099> | metrics |
| Tempo | <http://127.0.0.1:3200> | traces, MCP at `/api/mcp` |
| Pyroscope | <http://127.0.0.1:4040> | profiles |
| Loki | <http://127.0.0.1:3100> | logs |
| OTLP | `4317` gRPC, `4318` HTTP | ingest |

Grafana avoids 3000 and Prometheus avoids 9090 on purpose. Both defaults are
commonly taken on a dev box, and a taken port does not fail loudly: Docker still
publishes it, but a host process already bound there answers first. Queries then
reach the wrong server and return plausible data, which costs far more
debugging time than a refused connection. Override with
`LIBTMUX_LGTM_GRAFANA_PORT` and `LIBTMUX_LGTM_PROM_PORT` if these collide too.

`just otel-up` checks for this before reporting success, by comparing each
service's build info as seen from inside the container against the same URL
from the host. Run it alone at any time:

```console
$ just otel-ports
```

## What the workload emits

`scripts/otel_smoke.py` runs every transport — subprocess and control mode,
sync and async — against a throwaway tmux server, and emits four signals:

Metrics are `tmux_requests_total`, `tmux_commands_total`, `tmux_inlined_total`,
`tmux_failures_total`, and the `tmux_command_duration_seconds` histogram, each
labelled by `tmux_lane` and `tmux_command`.

Traces are one span per command, carrying `tmux.commands` and `tmux.inlined` so
TraceQL can find requests that batched work. The duration histogram records
while its span is current, which attaches an exemplar and gives Grafana the
metric-to-trace pivot.

Logs carry trace context, so a log line links to the trace it came from.

Streaming is measured separately, because notifications arrive out of band and
the instrumentation seam never sees them: a sink wraps `run()`, and nothing
routes a `%output` through `run()`. The workload therefore subscribes to
control-mode notifications while commands keep flowing, and records how many
arrived along with the engine's own count of any it had to drop because the
subscriber fell behind. Those two counters are written once per run, so their
panels read the last value in the window rather than an increase across it.

Profiles come from Pyroscope sampling the process, which is how "where did the
Python time go" gets answered — the engines' own frames show up in the flame
graph, tagged per transport, so a lane's CPU cost is as comparable as its
latency.

Allocation profiles are available too, but off by default because collecting
them costs more than CPU sampling:

```console
$ just otel-smoke --memory-profile
```

That adds the `memory:alloc_space`, `memory:alloc_objects`, and
`memory:inuse_space` profile types. They are per run rather than per transport:
the per-lane tag scopes the CPU sampler, and the allocation profiler does not
consult it. The other profile types Pyroscope lists — goroutines, mutex, block
— belong to Go runtimes and stay empty for a Python process.

The workload deliberately issues commands tmux rejects. A dashboard whose error
panel is empty is untested rather than healthy, so the failure path has to
produce real data.

## Identity: which fact rides on which signal

Every run is stamped with where it came from -- branch, revision, repository,
worktree, and optionally a spike name -- so two runs can be told apart and
compared. The interesting decision is not collecting that, it is choosing which
signal carries which fact, because the three fail differently when you get it
wrong.

| Fact | Metrics | Traces | Profiles |
| ---- | ------- | ------ | -------- |
| branch (`vcs.ref.head.name`) | yes | yes | yes |
| run id (`libtmux.run_id`) | yes | yes | yes |
| spike (`libtmux.spike`) | yes | yes | yes |
| revision (`vcs.ref.head.revision`) | **no** | yes | yes |
| worktree (`libtmux.worktree`) | **no** | yes | yes |
| test case, phase | **no** | yes | no |

A metric label is a stored time series forever, so the metric row is a budget
rather than a wish list. The test is "would I group by this?", not "is it
interesting?". A commit SHA fails that test: each run has exactly one, so
grouping by SHA is grouping by run, which the run id already does -- it would
add no query power while creating a fresh set of series on every commit. It
still rides on spans and profiles, where the drill-down happens and high
cardinality is expected. `scripts/lgtm/identity.py` owns the split, and a test
fails if the metric set grows.

Resolving all of it costs one `git rev-parse` at process start, a couple of
milliseconds, and nothing per tmux command: the labels are computed once and
merged into each point. `LIBTMUX_VCS_REF`, `LIBTMUX_VCS_REVISION`,
`LIBTMUX_WORKTREE`, and `LIBTMUX_SPIKE` override the detected values, which is
what CI wants -- it checks out a detached HEAD but knows the branch the work
belongs to.

### Baggage, for what changes mid-process

Branch and revision are fixed for a process, so they are resource attributes.
The test now running, or the phase a workload is in, are not -- and they should
not become parameters threaded through engine calls that have no business
knowing about telemetry.

`telemetry.scope()` puts them in OpenTelemetry baggage, and a span processor
copies the approved keys onto every span as it starts:

```python
with telemetry.scope(**{"libtmux.phase": "control-async"}):
    ...
```

Spans created anywhere inside that block carry `libtmux.phase`, queryable in
Tempo as `{ span.libtmux.phase = "control-async" }`. Only the keys in
`identity.BAGGAGE_KEYS` are copied, because baggage propagates across process
boundaries and an unrelated caller's entries should not silently become
attributes here. The cost is one context read per span, and when no baggage is
set the loop body never runs.

## Dashboards

Five boards, provisioned into the `libtmux` folder:

`libtmux / Home` is the entry point: which board answers which question, with
links. `libtmux / Overview` follows the RED method -- rate, errors, duration --
because an engine is a service, and its panels link down to the board that
explains them. `libtmux / Transports` compares the four transports
against each other. `libtmux / Commands` breaks the same work down by tmux
command. `libtmux / Compare` answers "is this different from that", grouping the
same measurements by run and by branch.

Every board carries Transport and Branch selectors, and Compare adds a Spike
selector to scope a comparison to one experiment.

The JSON is generated, not hand-written, by `generate_dashboards.py`. A board is
a few hundred lines of nested objects where panel placement is manual
arithmetic, so hand-maintaining three of them guarantees drift. Regenerate after
changing the generator:

```console
$ just otel-dashboards
```

`up.sh` regenerates on every start, and `tests/test_lgtm_dashboards.py` fails if
the committed JSON differs from what the generator produces, so the two cannot
diverge quietly. Editing a board in the Grafana UI is fine for exploring; move
the change into the generator to keep it.

## Load shaping: why rampa and not k6

`just otel-smoke` runs flat out for a fixed duration with a fixed number of
workers. That is a closed loop, and a closed loop hides saturation: as latency
rises the workers slow down with it, offered load falls, and the graph bends
politely instead of breaking.

`just otel-load` uses [rampa](https://github.com/tony/rampa) for the shapes
that expose it, notably `ramping-arrival-rate` -- an open model that keeps
issuing commands at a target rate whether or not the previous ones finished, so
latency climbs on its own once a transport saturates:

```console
$ just otel-load
```

The difference is visible: the same control-mode engine measures p99 around
2 ms under the steady workload and around 16 ms at the top of the ramp. Pick a
transport with `LIBTMUX_LOAD_LANE=subprocess-async`.

k6 was the obvious alternative and is the wrong tool here. Its value is HTTP
load at scale, and there is no HTTP surface in front of the engines -- driving
Python from k6 means a subprocess or an HTTP shim per iteration, which measures
the shim. rampa is Python, so it drives the engines in-process, and it
implements the same six executor models k6 defines.

rampa provides the schedule; telemetry still comes from this project's own
sink. That split is deliberate rather than a workaround: rampa's own OTLP
backend would export under its service name and its metric vocabulary, so a
load-shaped run would arrive as a second, parallel account of the same work.
Going through the sink instead means it lands under the same metric names and
the same branch, worktree, and spike labels as every other run, and the two are
directly comparable.

## Why the acceptance check exists

A dashboard that renders is not a dashboard that works. A panel whose query
returns nothing looks exactly like a panel reporting a healthy zero.

`scripts/otel_acceptance.py` reads the generated JSON, expands the template
variables the way Grafana would, runs every panel's own query against
Prometheus, Loki, Tempo, or Pyroscope, and fails naming any panel that returned
nothing. Because it reads the dashboards themselves, a panel added to the
generator is covered the moment it exists.

If the stack is not running the check says so and stops, rather than waiting
out a socket timeout per panel: a closed port is not always refused promptly,
so without that guard a forgotten `just otel-up` becomes a long silence ending
in a confusing report of empty panels.

Ingestion is asynchronous, and each backend buffers on its own schedule, so at
any single instant "no data yet" is indistinguishable from "no data ever". The
check therefore re-queries the panels that came back empty until they fill or
`--timeout` expires; a warm stack passes on the first sweep and a cold one waits
only as long as it needs. A cold-started Tempo is the usual reason for a
second pass.

## Querying it from an agent

Both Grafana and Tempo expose MCP servers, so an agent can ask the stack
questions directly instead of being handed screenshots. Print a client
configuration for this stack:

```console
$ just otel-mcp
```

Use its output rather than the one at `/etc/lgtm/mcp.json` inside the
container. The shipped config assumes Grafana is on its default port; this
stack moves it, so following the shipped copy connects to nothing and an agent
reports an empty stack rather than a misconfigured one.

The Grafana service account token is read from the running container each time
and is never stored in this repository.

Tempo's MCP server answers at `http://127.0.0.1:3200/api/mcp` and offers seven
tools, including `traceql-search`, `get-trace`, and `get-attribute-values`, so
the engine attributes are discoverable without knowing the schema in advance.
Asking it for `{ resource.service.name="libtmux-engines" }` returns the same
spans the dashboards draw.

## Configuration

`up.sh` pins the `grafana/otel-lgtm` image rather than tracking `latest`, so a
rerun sees the Prometheus and Pyroscope this stack was verified against. It
bind-mounts `grafana-datasources.yaml` (pinning the datasource uids every panel
binds to), `grafana-dashboards-libtmux.yaml` (the provider), and the generated
`dashboards/` directory.

The container carries a config label. Changing the mounted configuration means
bumping `CONFIG_LABEL` in `up.sh`, which makes the next `just otel-up` recreate
the container instead of restarting it with stale mounts.

Upstream image: <https://github.com/grafana/docker-otel-lgtm>
