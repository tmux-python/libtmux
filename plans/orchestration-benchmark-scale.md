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

## Open defect: stale-socket check rejects on mtime

`SocketIdentity` carries `st_mtime_ns`, and `_remove_proven_stale_socket`
compares whole identity values. Modification time is not an identity attribute —
it advances whenever the socket is used — so a socket whose device, inode, owner,
and mode are unchanged is still reported as
`configured socket ownership changed`, and the stale node is left in place.

Deterministic reproduction, no tmux required: bind a Unix socket, capture its
identity, advance its mtime by one millisecond with `os.utime`, then call
`_remove_proven_stale_socket` with an ownership record whose process is provably
absent. It returns `configured socket ownership changed` and leaves the socket
present, while device, inode, owner, and mode all compare equal.

Observed effect on real runs: an intermittent terminal `failed` status with
`failed_phase` of `cleanup`, in an artifact whose own retained `cleanup` object
simultaneously reports `complete` true and `socket_absent` true. That
self-contradiction is the signature. It struck roughly half of the longer runs
and is independent of whether the scratch root sits under `/tmp` or a home
directory; an early guess that the filesystem mattered came from a single
observation per location and does not survive the full tally.

Suggested fix, not yet implemented: compare the stable inode identity — device,
inode, owner, and mode — and keep `st_mtime_ns` as retained evidence rather than
as an equality key. Any change here needs a red test first, since this code
guards against deleting a socket the run does not own.

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

## Not implemented: the classic ORM reference

The design promises optional ORM cells measuring `server.sessions`,
`server.windows`, and `server.panes` as a reference alongside the typed
operations. No such cells exist in the runner. Note the naming trap: the
`classic` search family means tmux server-side format filtering, not the classic
ORM, so the presence of `search.classic.*` does not satisfy this.

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

## Outstanding before this is a reliable estate-wide benchmark

1. **Fix the stale-socket mtime comparison.** Until then roughly half of longer
   cells terminate `failed` on cleanup despite completing every phase, which
   corrupts any matrix summary that keys off overall status. Red test first.
2. **Implement the ORM reference cells**, or delete the promise from the design
   document. Today the third comparison cannot be made at all.
3. **Raise the sample count for the lane comparison.** Two samples cannot
   support the percentile columns the renderer prints. A four-lane cell at 15
   runs projects to roughly 44 minutes from per-iteration cost, but that
   projection is unreliable in the direction of underestimating, so measure it.
4. **Decide what the lane comparison is allowed to claim.** The subprocess lanes
   spend most of their time in capture, so a whole-iteration ratio mostly
   reports capture. Per-phase ratios are the defensible unit.
5. **Add a matrix-level renderer.** `matrix.json` currently holds per-cell
   summaries; there is no rendered cross-lane artifact equivalent to the
   single-cell Markdown report.
6. **Re-establish raw evidence durably.** The published n=100 raw JSON was lost
   to a host restart because it lived in a temporary directory. Only the
   committed renderer output survives.
