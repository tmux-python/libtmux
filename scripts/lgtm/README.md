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

Profiles come from Pyroscope sampling the process, which is how "where did the
Python time go" gets answered — the engines' own frames show up in the flame
graph.

The workload deliberately issues commands tmux rejects. A dashboard whose error
panel is empty is untested rather than healthy, so the failure path has to
produce real data.

## Dashboards

Three boards, provisioned into the `libtmux` folder:

`libtmux / Overview` is throughput, latency, failures, and the trace, log, and
profile panels side by side. `libtmux / Transports` compares the four transports
against each other. `libtmux / Commands` breaks the same work down by tmux
command.

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

## Why the acceptance check exists

A dashboard that renders is not a dashboard that works. A panel whose query
returns nothing looks exactly like a panel reporting a healthy zero.

`scripts/otel_acceptance.py` reads the generated JSON, expands the template
variables the way Grafana would, runs every panel's own query against
Prometheus, Loki, Tempo, or Pyroscope, and fails naming any panel that returned
nothing. Because it reads the dashboards themselves, a panel added to the
generator is covered the moment it exists.

Ingestion is asynchronous, and each backend buffers on its own schedule, so at
any single instant "no data yet" is indistinguishable from "no data ever". The
check therefore re-queries the panels that came back empty until they fill or
`--timeout` expires; a warm stack passes on the first sweep and a cold one waits
only as long as it needs. A cold-started Tempo is the usual reason for a
second pass.

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
