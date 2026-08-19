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

The predecessor `scripts/bench_engines.py` was archived because its numbers
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

## First cross-lane result

All four lanes complete at `80x20x1`. The subprocess lanes report 37 of 38
phases because `wait.control-stream` is `not_applicable` outside control/async,
which is the documented ruling rather than a failure; control/sync reports 37 for
the same reason.

Medians from a four-cell matrix at two timed runs and one warmup, same shape,
same seed. Treat these as directional: two samples support a median, not a
percentile.

| Phase (median) | subprocess/sync | subprocess/async | control/sync | control/async |
| --- | ---: | ---: | ---: | ---: |
| `mutation.bulk` | 750 ms | 913 ms | 5.9 ms | 6.2 ms |
| `capture.serial` | 21.1 s | 23.3 s | 13.7 s | 11.9 s |
| `capture.batched` | 20.7 s | 20.9 s | 1.03 s | 1.10 s |
| `search.classic.panes.middle` | 21.6 ms | 26.3 ms | 52.2 ms | 94.5 ms |
| `search.end-to-end.panes.middle` | 804 ms | 779 ms | 1124 ms | 1333 ms |
| Sum of timed phases | 49.2 s | 51.3 s | 24.6 s | 22.9 s |

Three readings, all of which need confirming at a real sample count:

1. **Control mode wins on many-small-command work.** `mutation.bulk` is roughly
   130 times faster on control lanes, because it issues many small commands and
   the subprocess lanes pay a fork for each one.
2. **Batching pays only where a persistent client exists.** Batched capture is
   11 to 13 times faster than serial on control lanes and within noise of serial
   on subprocess lanes, since a subprocess batch still starts one process per
   request. An earlier single-sample reading suggested batched was *slower* than
   serial on subprocess; at two samples it is parity, so that was noise.
3. **Control mode loses on single-shot queries.** Both `search.classic` and
   `search.end-to-end` are two to four times slower on control lanes. One
   isolated query does not amortize the persistent connection, and the connection
   is competing with the pane-output stream.

The wait comparison only exists on control/async: 6.8 ms for
`wait.control-stream` against 13.9 ms for `wait.capture-poll` in the same cell.

Search families differ by three orders of magnitude — 1.8 ms for in-memory
snapshot filtering, tens of milliseconds server-side, and roughly a second
end-to-end — which is why the report must never present them as one number.

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

1. **Publish a high-sample lane comparison.** A four-cell run at 20 timed
   samples is the first that can support p90 and p95; p99 needs 100 and is far
   more expensive. Project its wall time from a real matrix — a model built from
   single-run cells underestimated the subprocess lanes by about 80 percent,
   because warmup iterations cost more than steady-state ones.
2. **Re-establish raw evidence durably.** The published n=100 raw JSON was lost
   to a host restart because it lived in a temporary directory. Only the
   committed renderer output survives, and it still hashes to the value recorded
   when the artifact validated.
3. **Consider gating percentiles in the single-cell renderer too.** The matrix
   renderer now suppresses percentiles the sample count cannot support; the
   per-cell Markdown report still prints p95 and p99 unconditionally.
