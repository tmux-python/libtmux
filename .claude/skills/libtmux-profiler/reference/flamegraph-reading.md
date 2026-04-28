# Flamegraph & heatmap reading cheat sheet

A quick reference for interpreting Tachyon output. Read once, refer
back when staring at a fresh diff.

## Diff flamegraph color legend

Tachyon's `--diff-flamegraph` colors each frame by its delta vs.
the baseline binary file. Frame width represents the **current** run's
sample count (i.e. time spent now); the **color** tells you what
changed.

| color  | meaning                                                    |
|--------|------------------------------------------------------------|
| red    | regression — current took longer than baseline              |
| blue   | improvement — current took less than baseline               |
| gray   | minimal change — within sampling noise                      |
| purple | new code path — function appears only in current run        |

Darker red/blue = larger absolute delta. Hover any frame to see
`baseline_time / current_time / Δ%`.

If your optimization eliminates whole call chains, look for an
"elided" toggle — switching to elided view shows what disappeared
(the inverse of "purple"). Useful when verifying that a refactor
actually removed work rather than just shifted it.

## Frame width semantics

Width is sample count, which proxies time. Two frames at the same
width contributed equally to wall time at the chosen sampling rate.

A function's own width includes time spent in its callees. To see a
function's *exclusive* time, look at the difference between its width
and the sum of its children's widths — narrow leaves under a wide
parent mean the parent is doing real work itself, not just dispatching.

## Three common visual signatures

### "Wide flat plateau"

A single function spans most of the width with few or no children.

```
[          some_function          ]
[                ...               ]
```

→ The function itself is the bottleneck, or it's blocking on a
syscall. Common examples:
- `time.sleep` in a polling loop
- `selectors.select` waiting for I/O
- `os.read` on a pipe
- Whole-function bytecode in a tight Python loop

### "Tall narrow spike"

A deep call stack stacks vertically with each frame ~as wide as its
parent.

```
[              caller              ]
   [           callee              ]
      [        callee2             ]
         [     callee3             ]
            [    callee4           ]
               [   recursing_fn    ]
                  [recursing_fn]
                  ...
```

→ Often deep dispatch chains (pluggy hook flow, decorator stacks) or
recursion. The dispatch case is harmless overhead; recursion may
indicate algorithmic issue.

### "Many short equal-width bars"

A row of frames each ~the same narrow width, with similar callers
above.

```
[           outer_loop            ]
[a][b][c][d][e][f][g][h][i][j][k]...
```

→ A loop body, each call costing ~the same. Optimization target: the
loop itself, or replace with vectorized/batched alternative.

## Heatmap intensity

Heatmaps show sample counts per source line, color-graded:
- bright red / orange = many samples on that line
- yellow / green = moderate
- cool / gray = few or none

Source lines with no samples (dispatched but instant) appear cool.
Don't conflate "executed" with "expensive" — a one-line `return`
might run 10000× without ever showing up because each execution is
sub-microsecond.

With `--opcodes` enabled, hot lines expand to show per-bytecode-op
intensity. Useful for diagnosing surprising tight-loop costs (e.g.,
"why is this attribute access showing up?" → `LOAD_ATTR` repeated
across the loop).

## Quick pattern-matching to root cause

| visual signature | likely cause |
|---|---|
| wide plateau on `time.sleep` | speculative sleep, replace with `retry_until` |
| wide plateau on `selectors.select` | blocking I/O wait — look one frame up to find the caller |
| wide plateau on `subprocess.Popen.communicate` | child-process wait — engine is waiting for tmux, ssh, etc. |
| wide plateau on `os.fork` / `os.posix_spawn` | per-call process spawn overhead |
| tall spike through `pluggy._hooks.HookCaller.__call__` | normal pytest dispatch — usually not a bug |
| tall spike through `_pytest.fixtures.SubRequest.getfixturevalue` | fixture chain — heavy when many autouse fixtures |
| many narrow bars under `for ... in items` | loop body, optimize per-iteration cost |
| purple frames in diff against baseline | new code paths — verify they're intentional |

## When the signature is misleading

Sampling profilers undersample very-short-lived calls. A function
that runs 100,000 times for 5 µs each (500 ms total) may show
*fewer* samples than a function that runs once for 100 ms — because
the 5 µs slot rarely overlaps with a sampling tick. If the
flamegraph and your wall-time intuition disagree, double-check with
`profiling.tracing` (deterministic) or inline `time.perf_counter()`
brackets around the suspicious code.
