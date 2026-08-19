# Huge Active Orchestration Benchmark

## Purpose

Build a hermetic benchmark for long-lived tmux servers containing 80 to 100
sessions, 20 to 100 windows per session, and one to four panes per window. Every
pane remains active while the harness measures construction, mutation, waits,
enumeration, capture, and search.

The harness supports the full `100x100x4` topology: 100 sessions, 10,000
windows, and 40,000 panes. A successful smaller ramp step is not evidence that
the maximum completed. Reports distinguish an implemented ceiling, an attempted
shape, a completed shape, and a host-resource cutoff.

## Deliverables

- `scripts/orchestration_fuzzer.py`: a self-contained PEP 723 Rich workload
  generator with `preview` and `serve` commands.
- `scripts/bench_orchestration.py`: a self-contained PEP 723 benchmark with
  `plan`, `run`, and `ramp` commands.
- Focused unit and live-tmux tests for workload determinism, delayed matching,
  topology truth, phase correctness, cleanup, and machine-readable results.
- JSON results containing raw samples and environment/resource metadata.
- A Markdown summary generated from the JSON evidence after the large runs.

The new scripts remain separate from `scripts/bench_engines.py`. That script
measures repeated construction of short-lived topologies; this benchmark builds
one persistent active topology and performs several distinct workloads on it.

## Running the benchmark

Both programs are self-contained PEP 723 scripts. Run every command from the
repository root, because `run` and `ramp` re-invoke their own worker process.
Clear `TMUX` and `TMUX_PANE` so a run can never reach your interactive server;
the benchmark also unsets them itself before importing libtmux.

Preview the workload without starting tmux. This renders the same frames the
pane processes will follow:

```console
$ uv run python scripts/orchestration_fuzzer.py preview \
    --seed 20260818 \
    --duration 5
```

Inspect a topology and the host guard without writing anything. `plan` imports
no libtmux and starts no tmux server:

```console
$ uv run python scripts/bench_orchestration.py plan \
    --shape 80x20x1
```

Run a small smoke topology first. It exercises every phase in seconds:

```console
$ env -u TMUX -u TMUX_PANE uv run python scripts/bench_orchestration.py run \
    --shape 2x2x2 \
    --lane control \
    --mode async \
    --runs 3 \
    --warmup 1 \
    --output smoke.json
```

Run the large active cell. Async control mode keeps one persistent client and
attributes pipelined requests individually:

```console
$ env -u TMUX -u TMUX_PANE uv run python scripts/bench_orchestration.py run \
    --shape 80x20x1 \
    --lane control \
    --mode async \
    --runs 100 \
    --warmup 5 \
    --seed 20260818 \
    --output n100.json \
    --markdown-output n100.md
```

Attempt the canonical ramp, which cleans each disposable server before the next
shape and records a structured cutoff when a resource guard trips:

```console
$ env -u TMUX -u TMUX_PANE uv run python scripts/bench_orchestration.py ramp \
    --runs 5 \
    --warmup 1 \
    --output ramp.json
```

Compare every execution lane at one shape. Cells run strictly one at a time,
because overlapping scale runs perturb the timings they produce:

```console
$ env -u TMUX -u TMUX_PANE uv run python scripts/orchestration_matrix.py \
    --shape 80x20x1 \
    --runs 20 \
    --warmup 2 \
    --with-orm
```

Re-render a finished matrix without running anything:

```console
$ uv run python scripts/orchestration_matrix.py \
    --render-only
```

Find where the workload buckles and on which dimension. This is a pressure
test, not a comparison: each rung is a single invocation, so only the outcome
means anything:

```console
$ env -u TMUX -u TMUX_PANE uv run python scripts/orchestration_stress.py \
    --axis all \
    --budget-seconds 2400
```

Validate a finished artifact tree. `validate` is read-only and contacts no tmux
server:

```console
$ uv run python scripts/bench_orchestration.py validate \
    --input n100.json
```

Render Markdown from validated JSON. The destination is replaced atomically and
only after validation succeeds:

```console
$ uv run python scripts/bench_orchestration.py render \
    --input n100.json \
    --output n100.md
```

## Reading the evidence

Measured values live in the JSON artifact. Rendered Markdown is generated from
that artifact, so measured values are never hand-edited. A retained example
lives at `scripts/bench-results/orchestration-summary.md`.

Four distinctions matter when quoting a report.

A completed shape is not a completed maximum. `100x100x4` is supported and
selectable, but it is host-gated. Only an artifact whose requested and observed
topology are both exactly `100x100x4`, with `maximum_completed` true, shows that
the maximum ran. A successful smaller shape says nothing about a larger one, and
a resource cutoff is evidence about the host rather than a reporting failure.

Engine batching is not process reduction. A batch still issues one tmux request
per operation, and on the subprocess transport it starts one process per request,
so a batched capture costs the same forks as the serial one. Batching changes
dispatch shape; only the control-mode lanes share one persistent client across
requests. Reports record planner steps, engine batches, tmux requests, and known
process starts separately so the difference stays visible.

Configured delay is not waiter overhead. Each delayed-text sample reports the
configured delay, the generator's scheduling lateness, and the detection overhead
separately, so a deliberate wait is never presented as library cost. Compare
detection overhead between the two wait strategies, not total elapsed time.

A small difference is not a difference. Phase timings here are heavy tailed and
their run-to-run spread does not shrink much with more samples, so the matrix
report claims a ratio only when the two confidence intervals separate, and marks
everything else unresolved. Treat an unresolved row as "these lanes are the same
for this phase", not as a missing measurement.

In-memory filtering is not an end-to-end query. `QueryList` filtering over an
already materialized snapshot is reported in its own cells and is not equivalent
to a server-side format filter or to a list-then-filter round trip that must
reach tmux.

## Topology and scale

`SxWxP` denotes sessions, windows per session, and panes per window. Every
dimension is positive. The supported ranges are:

- sessions: 80 through 100 for large runs;
- windows per session: 20 through 100;
- panes per window: one through four;
- small shapes remain accepted for tests and smoke runs.

The canonical ramp is ordered by expected live-pane pressure:

| Shape | Sessions | Windows | Panes |
| --- | ---: | ---: | ---: |
| `80x20x1` | 80 | 1,600 | 1,600 |
| `100x20x1` | 100 | 2,000 | 2,000 |
| `80x20x2` | 80 | 1,600 | 3,200 |
| `80x50x1` | 80 | 4,000 | 4,000 |
| `80x20x4` | 80 | 1,600 | 6,400 |
| `80x100x1` | 80 | 8,000 | 8,000 |
| `100x50x2` | 100 | 5,000 | 10,000 |
| `100x100x2` | 100 | 10,000 | 20,000 |
| `100x100x4` | 100 | 10,000 | 40,000 |

`ramp` attempts shapes in order and cleans each disposable server before the
next. It records a structured cutoff when a resource guard trips or a topology
phase fails. An explicit `run --shape 100x100x4` remains available; the harness
does not silently replace it with a smaller scenario.

## Activity model

Launching Rich or `uv` in every pane would make interpreter memory the dominant
limit. Instead, one central Python process renders deterministic Rich frames
into append-only stream files. Pane processes use a lightweight `tail` command
to follow one stream. This keeps every pane's PTY active while retaining a
single controlled workload clock.

The fuzzer exposes four modes distributed round-robin by stable pane ordinal:

- `editor`: source paths, line numbers, cursor/status state, and scrolling
  libtmux source excerpts;
- `dev-server`: request, rebuild, warning, error, and recovery records;
- `installer`: resolve, download, build, and install progress;
- `delayed-match`: ordinary scrolling output followed by a unique sentinel at a
  configured monotonic delay, then more output.

The generator accepts a seed, frame rate, duration, output directory, delayed
match interval, and sentinel prefix. `preview` renders the same frames
interactively. `serve` starts paused, writes a ready marker, and begins only
after the benchmark releases its gate. Each wait sample writes an atomic,
run-scoped request with a unique request ID and sentinel. The generator appends
that sentinel after the requested monotonic delay and atomically publishes
request-specific scheduling and emission evidence. This permits independent
warmup and timed wait samples without restarting the active topology, and lets
the report separate configured delay, generator scheduling lateness, and waiter
detection overhead.

One selected pane follows a dedicated delayed-match stream. That makes the
sentinel unique across the server for pane-content search. Every other pane
follows one of the shared mode streams. Stream files stay bounded for the
benchmark duration; rotation is outside this benchmark's scope.

## Isolation and lifecycle

Every run uses a unique short socket path, an empty tmux configuration, and a
private scratch directory. The benchmark unsets `TMUX` and `TMUX_PANE` before
importing libtmux. It never contacts the ambient tmux server.

The lifecycle is:

1. validate the scenario and record the host resource envelope;
2. start the paused fuzzer and wait for its ready marker;
3. create the tmux server and complete the selected topology;
4. verify exact session, window, and pane counts plus pane-process liveness;
5. release the fuzzer and prove every pane displays the current activity epoch;
6. run the measured phases while activity continues;
7. stop the fuzzer, kill the isolated server, and remove scratch state;
8. verify the process, socket, and scratch directory are gone.

SIGINT, SIGTERM, phase errors, and resource cutoffs use the same cleanup path.
A small supervisor process owns the terminal report and monitors an isolated
worker process with progress events and identity-checked process records. This
lets the benchmark recover when a worker is cancelled or an engine call stops
making progress. The JSON report is written atomically at startup, after each
checkpoint, and after cleanup; it includes the failed phase and error summary
when the run does not complete.

## Engines and execution lanes

The primary lanes are sync and async subprocess engines and sync and async
control-mode engines. All lanes use the same typed operations and validate the
same live postconditions. The default large run uses async control mode because
it can keep one persistent client and attribute pipelined requests individually.

The classic ORM is an optional reference, requested with `--with-orm`. It adds
`enumeration.orm.sessions`, `enumeration.orm.windows`, and
`enumeration.orm.panes`, interleaved with the typed enumeration cells they are
compared against, and each sample must return exactly the rows the typed
operation returns before it is accepted. The reference is never a fifth lane:
{class}`~libtmux.Server` reaches tmux through its own request graph whichever
engine a run measures, so its timing is not mixed into engine speedup claims.
An artifact records the choice, and a validator derives the phase graph it
requires from that declaration.

Setup reports planner steps, engine batches, tmux requests, and known process
starts separately.

Take care with one name: the `classic` *search* family means tmux server-side
format filtering, not the classic ORM.

Activity files feed pane processes directly, so the fuzzer does not use the
engine under measurement. The tmux server still bears the intended PTY output
load.

## Measured phases

### Setup

Setup starts with a fresh server and ends after the exact topology exists. The
fuzzer remains paused, so setup measures construction rather than output load.
The report records one raw duration per fresh-server attempt, command counts,
and the resulting resource snapshot. Setup samples are never pooled with the
repeatable phase samples.

### Activity stabilization

This untimed correctness gate releases the fuzzer and waits until every pane's
capture contains the current epoch marker. It also checks `pane_dead`, pane PID,
fuzzer heartbeat, and sentinel uniqueness. Failure rejects the run before any
performance phase is reported as valid.

### Bulk mutation

Each iteration mutates the largest selected session while activity continues:

1. set a generation user option on the session;
2. rename every window by stable window ID;
3. set every pane title by stable pane ID;
4. verify the generation and names;
5. restore canonical window names and clear the generation marker.

The mutation count and target cardinalities are recorded. A failed or partial
request invalidates the sample.

### Delayed text wait

The waiter starts before the fuzzer's delayed stream is released. Two strategies
run as separately named cells:

- `capture-poll`: bounded `capture-pane` polling with a fixed cadence;
- `control-stream`: decoded control-mode output matched as it arrives.

Each result reports configured delay, actual emission time, detection time,
detection overhead, poll/frame count, timeout, dropped notifications, and exact
sentinel match. Deliberate delay is not counted as library overhead.

### Enumeration

Separate cells measure typed `ListSessions`, `ListWindows`, and `ListPanes`
operations. Optional ORM cells measure `server.sessions`, `server.windows`, and
`server.panes`. Every sample asserts the exact row count and a stable checksum
of object IDs before it is accepted.

The repeated “list panes” requirement is interpreted as listing all three tmux
hierarchy levels: sessions, windows, and panes.

### Capture contents

The harness captures a bounded visible/history range from every pane. It
measures serial and engine-batched request strategies separately, records total
bytes and lines, and verifies that every pane contains a current activity epoch.
Batching does not imply fewer subprocesses on the subprocess transport.

### Search

Search uses known targets placed at the beginning, middle, and end of stable
topology order. Separate cells measure:

- tmux server-side format filtering for a session, window, and pane;
- Python `QueryList` filtering over an already materialized snapshot;
- end-to-end list plus Python filtering;
- content search across captured pane text for the unique sentinel.

Each cell requires exactly the expected object and reports the scanned row or
pane count. In-memory filtering time is not presented as equivalent to an
end-to-end server query.

## Sampling and reporting

Repeatable phases use configurable warmups and timed iterations. Strategy order
is deterministically interleaved rather than running every sample of one
strategy first. Reports retain all raw nanosecond samples and render count,
minimum, mean, median, p90, p95, p99, and maximum. Large setup runs report their
individual durations rather than manufacturing percentiles from one attempt.

Each phase records:

- requested and observed topology;
- engine, mode, and strategy;
- operations, batches, tmux requests, and returned rows;
- bytes, lines, frames, polls, and dropped notifications where applicable;
- tmux-server RSS, process count, file descriptors, and host available memory;
- tmux and Python versions, CPU count, seed, command line, and git revision;
- correctness and cleanup status.

The Markdown report distinguishes local descriptive evidence from causal or
machine-independent performance claims.

## Resource guards

`plan` performs no tmux writes. It prints exact topology totals, predicted pane
processes, and a conservative request count. `run` and `ramp` sample available
memory, process limits, file-descriptor limits, and tmux-server liveness before
and after each major phase.

A ramp stops after cleaning the current server when:

- available memory falls below a configurable floor;
- pane or fuzzer processes die;
- setup makes no progress for the configured watchdog interval;
- exact topology or activity verification fails;
- the user interrupts the run.

The cutoff is evidence, not success. `--force-extreme` relaxes predictive
preflight refusal but does not disable cleanup, watchdogs, or correctness checks.
The default PID reserve is the larger of 1,024 processes and 15 percent of the
detected cgroup limit. The default memory floor is the larger of 4 GiB and 15
percent of detected physical memory. Missing resource probes remain explicit
unknown values rather than being treated as zero.

## Tests and verification

Pure tests cover scenario parsing, ramp order, deterministic workload frames,
sentinel timing metadata, sample statistics, resource-cutoff records, and JSON
serialization.

Live tests use small disposable topologies to prove:

- every fuzzer mode scrolls visible pane content;
- the delayed sentinel appears only after its configured gate and delay;
- both wait strategies find the same sentinel without false matches;
- setup, mutation, enumeration, capture, and search return exact counts;
- activity continues during mutation and query phases;
- failure and cancellation remove the server, fuzzer, tail processes, socket,
  and scratch directory;
- a hostile user tmux configuration cannot affect the run.

The final branch gate is formatting, Ruff, mypy, the complete pytest suite, and
the documentation build. Large benchmark artifacts are accepted only after a
validator confirms expected phase names, raw-sample counts, topology checks,
cleanup, and the absence of failed rows.

## Out of scope

- Claiming that one local machine establishes universal engine speedups.
- Treating an unattempted `100x100x4` topology as completed.
- Running one Python or `uv` process per pane.
- Changing libtmux's public wait or search API solely for benchmark convenience.
- Benchmarking remote tmux servers or multiple hosts in this iteration.
