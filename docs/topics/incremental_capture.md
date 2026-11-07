# Incremental history capture

{meth}`Pane.capture_since() <libtmux.Pane.capture_since>` returns new retained
history rows, an immutable cursor, and evidence describing their alignment
with the previous capture. It requires a connected tmux 3.8+ daemon; the
rest of libtmux still supports tmux 3.2a.

This selection is explicit: `grid="history"` reads the main grid's retained
physical scrollback rows. It excludes the visible screen and alternate
screen, keeps soft-wrapped rows separate, and uses tmux's default trailing
space trimming. A redraw or output that never enters retained history is
outside this selection. Other grid values raise `ValueError` before dispatch.

Run this standalone program from a checkout with libtmux installed:

```console
$ python examples/history_delta.py
```

The program owns a private server, feeds repeated rows to an empty pane,
checks the returned outcomes, and cleans up. Each native input command has
a half-second bound. Input completion is not evidence of a program's exit.

```{literalinclude} ../../examples/history_delta.py
:language: python
```

## Interpret the result

Always inspect `status` before treating `lines` or `text` as a delta.

| Status | Returned rows | Meaning |
| --- | --- | --- |
| `reset` | Current retained history | A new anchor. `reason="initial"` identifies the first call; other reasons identify a changed scope, geometry, generation, or an unqualified prior cursor. |
| `continuous` | Counter-aligned suffix | Sampled counters balance and retained rows agree. Evicting rows already read by the cursor does not imply a gap. |
| `gap` | Current retained history | Collection passed rows not yet read by the cursor. The discarded text cannot be recovered. |
| `unknown` | Captured history, when available | Missing counters, unverified identity, an observed race, or inconsistent history prevents alignment. Empty rows do not imply that nothing happened. |

Pass `result.cursor` into the next call. Each result and cursor is frozen;
previous values remain readable after the pane or server disappears. An
`unknown` cursor cannot qualify a later delta: the next stable capture
starts a new anchor. A failed command or missing pane raises
{class}`~libtmux.exc.LibTmuxException`; it does not return a successful empty
capture. An older connected daemon raises {class}`~libtmux.exc.VersionTooLow`.

## What continuity establishes

`continuous` describes agreement between the observed history samples.
It does **not** establish an atomic snapshot, a lossless output interval,
or a record of every row that appeared between calls. Metadata and capture
use separate commands. A detected change during capture returns `unknown`,
but unchanged metadata cannot rule out a complete resize/restore cycle or
an entire 32-bit counter cycle between observations.

For example, equal captures of five `same` rows can follow either two new
rows or many new rows. The counters distinguish ordinary eviction from a
collection gap. Equal row text alone cannot do that. Conversely, height
changes can move rows between history and the visible screen without
advancing the counters; the capture also checks geometry, history size,
and retained-row overlap. Unobservable intermediate rows remain outside
the promise. An observed alternate screen returns `unknown`; a complete
unobserved visit can leave main history unchanged.

The cursor binds to the selected local executable and endpoint, socket
device/inode/change timestamp, daemon identity, pane identity, and grid.
Changing a daemon or pane invalidates that binding. This relies on local
socket incarnation evidence and native identifiers, not PID alone. Native
IDs and counters are finite; these observations cannot prove that no
complete identifier cycle occurred. Native calls pin the resolved socket,
pane ID, and executable before capturing, so a caller's handle or environment
change cannot silently redirect the capture to another server. Missing
filesystem identity, unresolved relative executables, injected engines, and
custom `cmd()` dispatch return `unknown`. Custom commands still run through
the selected dispatcher and retain any successfully captured history; local
filesystem evidence never qualifies a potentially remote socket.

Every call rechecks the connected daemon and reads its retained history in
full. The result is incremental; transport and cursor storage scale with
retained history. Commands use the existing blocking dispatch behavior.
The decoded text is a terminal rendering, not the program's original bytes.

Native definitions and update sites:
[history formats](https://github.com/tmux/tmux/blob/3.8/format.c#L1909-L1937),
[collection and reset counters](https://github.com/tmux/tmux/blob/3.8/grid.c#L431-L559),
[height resizing](https://github.com/tmux/tmux/blob/3.8/screen.c#L409-L491), and
[native counter reconciliation](https://github.com/tmux/tmux/blob/3.8/window-copy.c#L450-L517).
