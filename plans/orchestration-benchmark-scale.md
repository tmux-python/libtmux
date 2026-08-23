# Orchestration benchmark: scale ceiling and open defects

Working notes for the active orchestration benchmark
(`scripts/bench_orchestration.py`). These are engineering notes, not user
documentation; the user-facing page is
`docs/experimental/orchestration-benchmark.md`.

## Why this benchmark exists

It measures libtmux's typed operations across the four execution lanes —
subprocess and control mode, each sync and async — against one persistent,
continuously active tmux server. The comparisons that matter are internal to
libtmux:

1. lane against lane, all running the same typed operations and validating the
   same live postconditions;
2. strategy against strategy inside a phase: serial against batched capture,
   capture-poll against control-stream waiting, and server-side format filtering
   against in-memory `QueryList` filtering against an end-to-end round trip;
3. the classic ORM as an optional reference, deliberately kept out of engine
   speedup claims when its request graph differs.

The predecessor `scripts/bench/engines.py` was archived because its numbers
measured transport and tmux server cost while being labelled as planner
optimization. That is the mistake this harness exists to avoid, which is why it
reports planner steps, engine batches, tmux requests, and process starts as
separate quantities.

## Measured scale ceiling

Two ceilings, an order of magnitude apart. Do not conflate them.

**Harness measurability: between 2,000 and 2,500 panes** on the development
host. At one timed run and no warmups, control/async: 1,600 panes completes
three of three attempts; 2,000 completes every phase but runs roughly five times
slower per iteration; 2,400 and 2,500 fail at `capture.batched`; 3,000 fails at
`mutation.bulk`; 3,200 fails non-deterministically at either
`wait.control-stream` or `mutation.bulk`; 6,400 fails at `stabilization`. Every
failure is the fixed 30-second control-mode timeout, never resource exhaustion.

**Raw host capacity: about 32,000 panes**, where `fork` returns `EAGAIN`.
Memory is linear at roughly 0.41 MB per pane and never binds; pseudoterminals
cap at 65,536 and never bind. The binding limit is the control group task
budget, which is also why `plan` predictively refuses `100x100x4`.

`80x20x1` is simultaneously the smallest shape in the documented large-run range
and the largest reliably measurable one on this host.

## The axis is pane count, through tmux's single-threaded server

Ruled out by measurement rather than assumed:

- Not the control client. Muting `%output` speeds sequential capture by only
  1.0 to 1.2 times.
- Not output volume. 1,600 panes burn 89.1 percent of a core at 10 Hz and only
  93.6 percent at 40 Hz, so reads coalesce. Lowering the fuzzer frame rate buys
  no scale; this was tested before proposing it as a remedy.
- Not host memory or process limits, as above.

Confirmed instead: the tmux server pegs 97 to 99 percent of one core at both
1,600 and 2,000 panes while load average sits near 2.5 on twenty cores. A
zero-output control isolates the per-pane cost — idle panes alone give 10.2
percent CPU and a 4.2 ms command round trip at 800 panes, 17.6 percent and
8.0 ms at 1,600, 33.2 percent and 22.8 ms at 3,200, and 57.0 percent and 63.2 ms
at 6,400.

Because phases issue one command per pane sequentially while per-command latency
itself grows with pane count, phase cost grows roughly with the square of pane
count until it trips the fixed timeout. `capture.serial` is the wall: it is the
only phase that is strictly one round trip per pane, it is 39 percent of an
iteration at 1,600 panes, and it jumps from 8.7 to 81.4 seconds between 1,600
and 2,000 panes at an identical 87 lines per pane.

Raising the ceiling needs harness changes, not a larger machine: timeouts scaled
to topology, and a capture phase that does not require one round trip per pane.

## Fixed: stale-socket check rejected on tmux's own mode churn

The cleanup defect was upstream behaviour, not a race, and not the timestamp it
first appeared to be.

`server_update_socket()` in tmux sets the socket's execute bits while any
session is attached and clears them when none is. Measured directly: a socket is
mode 0600 with no client, 0700 while a control client is attached, and 0600
again after it detaches, with **mtime unchanged throughout** — only ctime moves,
because the mechanism is `chmod`, not `utimes`. `SocketIdentity` compared the
complete mode, so an ordinary attach or detach read as a different socket and
cleanup refused to remove a node it owned. That is why control lanes, which hold
a persistent client, were the ones affected, and why the incidence tracked run
length rather than filesystem.

Two earlier readings were wrong and are recorded because both were plausible:

- *"It is an mtime race."* A synthetic probe advancing mtime did reproduce the
  rejection, but only because mtime was one member of an over-specified tuple.
  In real runs mtime never moved.
- *"Put scratch under `/tmp`."* Across the full tally `/tmp` failed once in four
  and a home directory failed three times in seven. The location never mattered;
  that conclusion came from one observation per location.

The fix compares device, inode, owner, file type, and modification time, and
excludes permission bits alone. Modification time stays load-bearing: the
retained inode-reuse regressions distinguish an original node from a later
replacement by timestamp only, and dropping it broke them. Both directions have
red proofs — comparing whole modes breaks the attach case, dropping mtime breaks
reuse detection — so the exclusion is exactly minimal.

This finding is about tmux rather than libtmux and is worth carrying into the
tmux notes: any tool that fingerprints a tmux socket by whole mode will see
phantom ownership changes whenever a client attaches or detaches.

## Cross-lane result at twenty samples

Four cells, 800 live panes (`40x20x1`), 20 timed samples and 2 warmups each,
23m46s wall. All four completed; the reference cells were included. Ratios below
are rendered only where the intervals separate — anything inside the run-to-run
spread is reported as unresolved rather than as a number.

| Phase | control/async | control/sync | subprocess/async | subprocess/sync | Spread |
| --- | ---: | ---: | ---: | ---: | ---: |
| `mutation.bulk` | 3.1 ms | 3.3 ms | 185.0 ms | 186.2 ms | 59.1x |
| `capture.batched` | 154.7 ms | 156.6 ms | 3548.4 ms | 3638.2 ms | 23.5x |
| `capture.serial` | 1046.5 ms | 975.9 ms | 3565.2 ms | 3677.1 ms | 3.8x |
| `enumeration.panes` | 256.2 ms | 251.9 ms | 232.8 ms | 236.4 ms | unresolved |
| `enumeration.sessions` | 14.2 ms | 14.2 ms | 16.2 ms | 15.3 ms | unresolved |
| `wait.capture-poll` | 7.0 ms | 6.5 ms | 8.6 ms | 6.2 ms | unresolved |

**This corrects an earlier claim.** A two-sample matrix appeared to show the
subprocess lanes winning every enumeration and search phase by 1.1x to 3.2x.
At twenty samples those differences are unresolved: they were noise, and the
renderer now refuses to print them. Control mode wins where the request pattern
rewards a persistent client, and ties elsewhere. It does not lose.

### Strategy comparisons

| Comparison | control/async | subprocess/sync |
| --- | ---: | ---: |
| serial capture over batched capture | 6.6x | 1.0x |
| capture polling over the notification stream | 5.3x | not applicable |

Batching pays only where a persistent client can pipeline. On the subprocess
transport a batch still starts one process per request, so it buys nothing.

### The classic ORM reference

Enumerating panes through `Server.panes` costs 0.91x the typed operation on
control/async and 1.11x on subprocess/sync — inside the noise on both. The typed
seam is therefore free at the enumeration level while being dramatically cheaper
where request patterns matter. That is the answer the third comparison exists to
give.

## Where each axis buckles

A separate ladder escalates one dimension at a time at a single timed
invocation, because only the outcome matters. Nine minutes for all three axes.

| Axis | Last completed | First failure | Surrendered at |
| --- | --- | --- | --- |
| panes per window | `80x20x1`, 1,600 | `80x20x2`, 3,200 | `wait.capture-poll` |
| windows per session | `80x20x1`, 1,600 | `80x30x1`, 2,400 | `capture.serial` |
| sessions | `100x20x1`, 2,000 | `140x20x1`, 2,800 | `wait.capture-poll` |

The ceiling is roughly two thousand panes on every axis, but the failure mode
differs. Adding windows survives nine of ten phases before serial capture gives
out, while adding panes per window or sessions dies early in the wait phase.
Attributing a ceiling to "panes" alone would have missed that.

## Implemented: the classic ORM reference

`--with-orm` adds `enumeration.orm.sessions`, `enumeration.orm.windows`, and
`enumeration.orm.panes`, interleaved with the typed enumeration cells they are
compared against. Every sample must return exactly the rows the typed operation
returns, which is the only reason the reference is comparable at all.

The reference is not a fifth lane. `Server` reaches tmux through its own request
graph whichever engine a run measures, so its timing is never folded into an
engine speedup claim.

An artifact records the choice as `orm`, and the required phase graph,
interleaving groups, and fuzzer service budget are all derived from that
declaration rather than from a fixed 38-phase constant. The report schema moved
to 3 for this reason.

The naming trap that hid the gap: the `classic` *search* family means tmux
server-side format filtering, not the classic ORM, so `search.classic.*` looked
like the promise was already kept.

## How to run this safely

Use `scripts/orchestration_matrix.py`. It measures nothing itself; it supervises
`bench_orchestration.py` so a comparison can be started without the hazards that
made every ad-hoc invocation here unreliable. It holds an exclusive lock so two
scale runs cannot overlap, clears `TMUX` and `TMUX_PANE`, keeps scratch short
enough that a socket path stays under the kernel's 107-byte limit, writes
evidence to a durable directory instead of a temporary one, removes scratch on
success, failure, and interrupt alike, and audits for residue afterwards. Cells
run strictly one at a time.

Two configurations are verified:

- **Single lane, real sample count, under ten minutes.** `80x20x1`,
  control/async, 15 runs and 2 warmups. Verified twice at 7m25s and 7m27s,
  validating as `completed` with all 38 phases, 540 timed samples across 36
  cells, zero dropped notifications, and exact cleanup. This answers the
  strategy comparisons but not the lane comparison.
- **All four lanes.** `80x20x1`, 2 runs and 1 warmup, measured at 15.9 minutes
  wall. This answers the lane comparison but supports only medians.

At fifteen samples quote minimum, median, and p90 only; the rendered p95 and p99
columns are not meaningful at that count, and at two samples only the median is.

A cost model taken from single-run cells underestimated the subprocess lanes by
about 80 percent, because warmup iterations cost more than steady-state ones.
Project matrix wall time from a real matrix, not from single-run timings.

## What the lane comparison may claim

The unit is the individual phase, never a summed iteration. Capture dominates
every lane's iteration, so a summed ratio is mostly a report about capture
wearing a label about transports.

The first four-cell evidence shows why that matters. Async control mode wins
`mutation.bulk` by roughly 140 times and `capture.batched` by roughly 20, while
the subprocess lanes win every enumeration and every search phase by 1.1 to 3.2
times. Both halves are true, and a single number reports neither. The rendered
report therefore names the winning cell per phase, reports slowest over fastest
as spread, and states that a per-phase ratio speaks only about that phase's
request pattern on that transport, on this host, at this topology.

Percentile columns are gated on sample count: a percentile at quantile `q` needs
at least `1 / (1 - q)` observations before it is anything other than the maximum
relabelled. Two samples render a median alone.

## Still outstanding

1. **Re-establish raw evidence durably.** The published n=100 raw JSON was lost
   to a host restart because it lived in a temporary directory. Only the
   committed renderer output survives, and it still hashes to the value recorded
   when the artifact validated.
2. **Consider gating percentiles in the single-cell renderer too.** The matrix
   renderer suppresses percentiles the sample count cannot support and refuses
   ratios inside the noise; the per-cell Markdown report still prints p95 and
   p99 unconditionally.
3. **Raise the harness ceiling if larger shapes matter.** That needs timeouts
   scaled to topology and a capture phase that is not one round trip per pane.
   No sample count or larger machine substitutes for it.

## Why the supervisor checks its child interpreter

Three strategies were built and compared before this landed.

**Declare libtmux in PEP 723 metadata** so the scripts run standalone. uv does
honour `[tool.uv.sources]` in inline metadata, and a relative path resolved the
working tree editable, so this worked — but only after also spawning children
through `uv run --script`, which puts uv on the runtime path and pays a
resolution per child. It also moves interpreter selection into PEP 723, which
is the layer that selects a free-threaded build in the first place.

**Drop the `--script` shebangs** so the broken path is unreachable. It is not:
`uv run --script` still works with the metadata gone, it simply runs bare. This
removed one entry point, not the trap.

**Check before spawning** — what shipped. It is entry-point agnostic, additive,
and matches the harness's existing posture of refusing loudly rather than
limping. The other two would win only under different premises: dropping the
shebang if it were the sole route to the broken interpreter, and PEP 723 if
these scripts were meant to run outside a checkout, which `run` and `ramp`
cannot.

The contest also surfaced the free-threaded interpreter finding, which no
amount of reading would have produced: it only appears in a fresh checkout,
because the working `.venv` predates it.

## Sizing runs

Sample counts are chosen from measured variance, not from taste.

Bootstrapping the retained fifteen-sample cell shows the median's spread barely
improves past ten observations on the noisy phases: bulk mutation stays near 85
percent and session enumeration near 43. The variance is run-to-run, not
sampling noise that averages away, so raising the count buys very little. Twenty
observations is the point where p90 and p95 become reportable at all; p99 needs
one hundred and is not worth its wall time here.

Cost is superlinear in panes, so shape is the cheaper lever. Subprocess costs
9.2 seconds per iteration at 800 panes and about 49 at 1,600. The comparison
therefore runs at 800 panes, where four cells at twenty samples finish in under
half an hour, while the pressure ladder runs at whatever shape the rung
requires because each rung is a single invocation.

Project wall time from a real matrix. A model built from single-run cells
underestimated the subprocess lanes by about 80 percent, because warmup
iterations cost more than steady-state ones.
