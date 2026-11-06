(pane-interaction)=

# Pane interaction

A {class}`~libtmux.Pane` is a live terminal you drive from Python: you type into
it, read back what it printed, resize it, and tear it down when you're finished.
That makes the pane the unit you reach for when automating a shell, testing a
CLI, or orchestrating a terminal workflow.

Most of that work is two methods — {meth}`~libtmux.Pane.send_keys` to type and
{meth}`~libtmux.Pane.capture_pane` to read the screen back. If those two cover
you, you can stop after the first two sections; everything below is for the
rarer cases — waiting on output, querying a pane's state, resizing, and cleanup.

To follow along live, open two terminals.

In the first, start tmux:

```console
$ tmux
```

In the second, start `python` (or `ptpython`, if you have it):

```console
$ python
```

## Owning a fresh program

On tmux 3.8 or later, {meth}`~libtmux.Session.run_program` starts a program in a
new detached pane and returns an owned handle. It establishes pane retention
and exit observation before launching the program. `run_program` returns after
launch; call `wait()` for its eventual exit status or signal.

```python
>>> import sys
>>> from libtmux.common import has_gte_version
>>> if has_gte_version("3.8"):
...     job = session.run_program([
...         sys.executable, "-c", "print('finished'); raise SystemExit(7)"
...     ])
...     result = job.wait(timeout=1)
...     assert result.exit_status == 7
...     observation = job.collect(start=-100)
...     assert "finished" in observation.text
...     job.cleanup()
```

The [standalone program example](https://github.com/tmux-python/libtmux/blob/master/examples/owned_program.py)
creates a private server and session, checks status 7 and rendered output,
then removes its resources. It retains operation and cleanup failures together.
Its parent session survives job cleanup:

```console
$ python examples/owned_program.py
```

Pass a program and at least one argument. Arguments keep spaces, empty strings,
shell metacharacters and literal dollar signs. To use shell syntax, pass an
explicit shell invocation such as `["sh", "-c", "printf hello"]`.

The handle's operations have separate effects:

| Operation | Result and resource policy |
| --- | --- |
| `wait(timeout=5, cancel_event=None)` | Immutable `pane_id`, `exit_status` and `exit_signal` fields. A signal retains tmux's spelling, which can be a name or a decimal number. |
| `collect(start=-1000, end="-", max_text_codepoints=1048576, timeout=5)` | Immutable rendered observation with `lines`, `text`, `pane_id`, actual `command`, selection fields, and monotonic `started_ns`/`finished_ns`. Wrapped rows are joined. |
| `terminate(timeout=5)` | Closes the positively owned pane and PTY, then reaps its observer clients. Returns `pane_removed` and any exit evidence already obtained. It does not establish that all descendant processes exited. |
| `cleanup(timeout=5)` | Removes a completed retained pane and reaps its observer clients. A running program requires explicit `terminate()` first. The borrowed session and other panes survive. |

Collect output before termination. Capture includes only the selected retained
history and screen, not a lossless byte stream. tmux's inherited history limit
still governs what the pane retains; this helper does not change the parent
session's history policy. `start` and numeric `end` must lie within
`[-10000, 10000]`. Decoded capture is admitted up to `max_text_codepoints`, which
must lie in `[1, 1048576]`. The separate transport limit is four times that value
plus 65536 bytes; client diagnostics and observer streams each have a 16384-byte
limit. These limits bound collection, not the tmux daemon's total memory.
`target_lifetime_verified` in the observation remains `None`; it is compatible
with the retained pane-observation shape and does not claim a general tmux
object-lifetime proof.

A `threading.Event` cancels a wait without stopping the program or closing its
handle-owned observers. Clear the event and wait again, or terminate explicitly.
Cancelling a worker thread's future does not set this event. Timeouts raise
{exc}`~libtmux.exc.WaitTimeout`; cancellation raises
{class}`concurrent.futures.CancelledError`. Other operational failures retain
the {exc}`~libtmux.exc.LibTmuxException` catch contract. Exceptions expose
`last_observation`, `last_capture`, `operation_error`, `cleanup_errors` and
`owner`, with the original cause in `__cause__`. `None` means no observation was
obtained; an empty capture is a distinct immutable value. Keyboard interruption
preserves the original `KeyboardInterrupt` object.
Use one caller at a time for a handle; concurrent methods and reuse after a
process fork are not supported.

The handle freezes its selected executable, endpoint and environment. A random
window name is installed by the original creation command and retained as
ownership evidence. Renaming or moving the pane can invalidate this evidence;
the helper refuses an unproved destructive operation. It never cleans up by a
reused name or numeric ID alone, and an accepted creation with a missing receipt
stays uncertain. Setup failure compensates only positively identified creation
and retains cleanup failures alongside the original error. Custom dispatchers
and injected engines are refused before native effects.

Deletion consumes the handle's still-pending lifetime waiter and closes its
pane in one native command queue. A respawn or lost observer makes that
registration unavailable, so `terminate()` and `cleanup()` refuse deletion and
reap their owned clients. A submitted launch whose readiness was lost follows
the same rule: missing proof can leave its pane running, with cleanup failure
retained for explicit inspection.

Calling `cleanup()` while the verified program is still running leaves its
observers usable for another wait or explicit termination. Ownership loss or an
unreachable daemon instead closes the owned clients and retains the failure;
it does not authorize deleting an unproved replacement.

Exit evidence comes from a selected native event and a queued retained-status
readback. A second observer is registered in the launch command queue to detect
later respawns of the same pane. Missing, replaced or lost evidence stays
unknown. An unrelated pane's exit, an early control reply, or visible text cannot
substitute for the selected program's exit. Sending commands into an existing
interactive shell remains a separate operation.

## Sending commands

{meth}`~libtmux.Pane.send_keys` types text into the pane exactly as if you had
typed it at the keyboard, and by default presses Enter so the shell runs it.
That default is what you want most of the time: hand it a command string and it
executes. The arguments below come into play only when you need to type without
running, send characters tmux would otherwise interpret, or invoke send-keys
purely for its flags.

### Basic command execution

```python
>>> pane = window.split(shell='sh')

>>> pane.send_keys('echo "Hello from libtmux"')

>>> import time; time.sleep(0.1)  # Allow command to execute

>>> output = pane.capture_pane()
>>> 'Hello from libtmux' in '\\n'.join(output)
True
```

### Send without pressing Enter

Sometimes you want the text sitting at the prompt without running it — to stage
a command, or to feed a keystroke a running program is waiting on. Pass
`enter=False` to type without pressing Enter:

```python
>>> pane.send_keys('echo "waiting"', enter=False)

>>> # Text is typed but not executed
>>> output = pane.capture_pane()
>>> 'waiting' in '\\n'.join(output)
True
```

When you're ready to run it, press Enter on its own with
{meth}`~libtmux.Pane.enter`:

```python
>>> import time

>>> # First type something without pressing Enter
>>> pane.send_keys('echo "execute me"', enter=False)

>>> pane.enter()  # doctest: +ELLIPSIS
Pane(%... Window(@... ..., Session($... ...)))

>>> time.sleep(0.2)

>>> output = pane.capture_pane()
>>> 'execute me' in '\\n'.join(output)
True
```

### Literal mode for special characters

Both tmux and your shell interpret certain characters. Pass `literal=True` to
send them through untouched, so a tab or escape arrives as the literal byte
rather than a key tmux acts on:

```python
>>> import time

>>> pane.send_keys('echo "Tab:\\tNewline:\\n"', literal=True)

>>> time.sleep(0.1)
```

### Suppress shell history

Pass `suppress_history=True` to prepend a space before the command. In a shell
configured to ignore space-prefixed lines, that keeps the command out of your
history — useful when the command carries a secret:

```python
>>> import time

>>> pane.send_keys('echo "secret command"', suppress_history=True)

>>> time.sleep(0.1)
```

### Flag-only invocation

Sometimes you want send-keys only for its side effects — resetting the pane or
repeating the last key — and have no text to type. Pass `cmd=None` to invoke it
for the flags alone:

```python
>>> # Repeat the last key 5 times (-N 5)
>>> pane.send_keys(cmd=None, repeat=5)

>>> # Reset the pane to default state (-R)
>>> pane.send_keys(cmd=None, reset=True)
```

`cmd=None` requires at least one of `reset=True`, `repeat=N`, or
`copy_mode_cmd=...`; calling it with no flag raises `ValueError` to
prevent silent no-ops.

## Capturing output

{meth}`~libtmux.Pane.capture_pane` reads the pane's screen back to you as a list
of lines — one string per row, top to bottom. With no arguments you get the
visible screen, which is what most reads want. The parameters below extend that
reach: into scrollback, keeping color, stitching wrapped lines, or preserving
spacing. Reach for them only when a plain capture drops something you need.

### Basic capture

```python
>>> import time

>>> pane.send_keys('echo "Line 1"; echo "Line 2"; echo "Line 3"')

>>> time.sleep(0.1)

>>> output = pane.capture_pane()
>>> isinstance(output, list)
True
>>> any('Line 2' in line for line in output)
True
```

### Capture with line ranges

By default you read the visible screen. Pass `start` and `end` to widen or
narrow that window — negative numbers count back from the visible region, and
`'-'` reaches the start of history or the current line:

```python
>>> # Capture last 5 lines of visible pane
>>> recent = pane.capture_pane(start=-5, end='-')
>>> isinstance(recent, list)
True

>>> # Capture from start of history to current
>>> full_history = pane.capture_pane(start='-', end='-')
>>> len(full_history) >= 0
True
```

### Capture with ANSI escape sequences

A plain capture strips color and formatting, handing you clean text. When you
need the styling instead — to assert a prompt really printed in red — pass
`escape_sequences=True` to keep the ANSI codes intact:

```python
>>> import time

>>> pane.send_keys('printf "\\033[31mRED\\033[0m \\033[32mGREEN\\033[0m"')
>>> time.sleep(0.1)

>>> # Capture with ANSI codes stripped (default)
>>> output = pane.capture_pane()
>>> 'RED' in '\\n'.join(output)
True

>>> # Capture with ANSI escape sequences preserved
>>> colored_output = pane.capture_pane(escape_sequences=True)
>>> isinstance(colored_output, list)
True
```

### Join wrapped lines

A line longer than the pane wraps onto several rows, and a plain capture returns
it as several strings. Pass `join_wrapped=True` to stitch those rows back into
one logical line:

```python
>>> import time

>>> # Send a very long line that will wrap
>>> pane.send_keys('echo "' + 'x' * 200 + '"')
>>> time.sleep(0.1)

>>> # Capture with wrapped lines joined
>>> output = pane.capture_pane(join_wrapped=True)
>>> isinstance(output, list)
True
```

### Preserve trailing spaces

By default, trailing spaces are trimmed. Use `preserve_trailing=True` to keep them:

```python
>>> import time

>>> pane.send_keys('printf "text   \\n"')  # 3 trailing spaces
>>> time.sleep(0.1)

>>> # Capture with trailing spaces preserved
>>> output = pane.capture_pane(preserve_trailing=True)
>>> isinstance(output, list)
True
```

### Capture flags summary

The full set of capture flags, and the tmux flag each one maps to:

| Parameter | tmux Flag | Description |
|-----------|-----------|-------------|
| `escape_sequences` | `-e` | Include ANSI escape sequences (colors, attributes) |
| `escape_non_printable` | `-C` | Escape non-printable chars as octal `\xxx` |
| `join_wrapped` | `-J` | Join wrapped lines back together |
| `preserve_trailing` | `-N` | Preserve trailing spaces at line ends |
| `trim_trailing` | `-T` | Trim trailing empty positions (tmux 3.4+) |
| `pending` | `-P` | Dump the unprocessed input buffer instead of the screen |

:::{note}
The `trim_trailing` parameter requires tmux 3.4+. If used with an older version,
a warning is issued and the flag is ignored.
:::

### Capturing the pending input buffer

For the rarer case where you need what tmux has read but not yet drawn, pass
`pending=True`. It dumps bytes tmux has buffered in its parser but
not yet committed to the pane's terminal — input the tmux process read
from the pane's PTY but hasn't fed through its escape-sequence parser
into the visible screen. Use it to inspect partial control sequences
mid-write.

```python
>>> pending = pane.capture_pane(pending=True)
>>> isinstance(pending, list)
True
```

`pending=True` is mutually exclusive with the line-range and screen-mode
flags (`start`, `end`, `escape_sequences`, etc.) — tmux ignores them when
`-P` is set.

## Waiting for output

tmux runs commands asynchronously: {meth}`~libtmux.Pane.send_keys` returns the
moment the keystrokes are sent, not when the command finishes. So when a later
step depends on a command completing, you wait for proof in the output rather
than guessing at a fixed delay.

The honest cost is that this means polling — capturing the pane on a short
interval until a marker you control appears. It's a busy wait, not an event, but
it's reliable across shells and commands because you're checking the one thing
that matters: what actually printed.

### Polling for completion marker

```python
>>> import time

>>> pane.send_keys('sleep 0.2; echo "TASK_COMPLETE"')

>>> # Poll for completion
>>> for _ in range(30):
...     output = pane.capture_pane()
...     if 'TASK_COMPLETE' in '\\n'.join(output):
...         break
...     time.sleep(0.1)

>>> 'TASK_COMPLETE' in '\\n'.join(output)
True
```

### Helper function for waiting

Wrapping that loop in a helper keeps the pattern out of the way of your actual
logic:

```python
>>> import time

>>> def wait_for_text(pane, text, timeout=5.0):
...     """Wait for text to appear in pane output."""
...     start = time.time()
...     while time.time() - start < timeout:
...         output = pane.capture_pane()
...         if text in '\\n'.join(output):
...             return True
...         time.sleep(0.1)
...     return False

>>> pane.send_keys('echo "READY"')
>>> wait_for_text(pane, 'READY', timeout=2.0)
True
```

## Querying pane state

{meth}`~libtmux.Pane.display_message` asks tmux to evaluate a format string
against the pane and hand back the result — its size, working directory, process
id, and the rest of tmux's `#{pane_*}` variables. Pass `get_text=True` to get
the answer as a list of strings.

Each call is a round-trip to tmux, which is exactly what you want for state that
moves as you watch it — dimensions during a resize, the working directory after
a `cd` — since you get a fresh reading rather than a value cached when the object
was built.

### Get pane dimensions

```python
>>> width = pane.display_message('#{pane_width}', get_text=True)
>>> isinstance(width, list) and len(width) > 0
True

>>> height = pane.display_message('#{pane_height}', get_text=True)
>>> isinstance(height, list) and len(height) > 0
True
```

### Get pane information

```python
>>> # Current working directory
>>> cwd = pane.display_message('#{pane_current_path}', get_text=True)
>>> isinstance(cwd, list)
True

>>> # Pane ID
>>> pane_id = pane.display_message('#{pane_id}', get_text=True)
>>> pane_id[0].startswith('%')
True
```

### Common format variables

A few of the format variables you'll reach for most often:

| Variable | Description |
|----------|-------------|
| `#{pane_width}` | Pane width in characters |
| `#{pane_height}` | Pane height in characters |
| `#{pane_current_path}` | Current working directory |
| `#{pane_pid}` | PID of the pane's shell |
| `#{pane_id}` | Unique pane ID (e.g., `%0`) |
| `#{pane_index}` | Pane index in window |

## Resizing panes

{meth}`~libtmux.Pane.resize` changes how much of the window a pane occupies. It
covers three needs through one method: set an exact size, nudge a dimension by a
relative amount, or toggle zoom to make the pane fill the window and back. The
result is bounded by the window and the pane's neighbors — tmux grants the space
it can, so treat a resize as a request, not a guarantee.

### Resize by specific dimensions

```python
>>> # Make pane larger
>>> pane.resize(height=20, width=80)  # doctest: +ELLIPSIS
Pane(%... Window(@... ..., Session($... ...)))
```

### Resize by adjustment

To grow or shrink a pane relative to its current size, name a direction from
{class}`~libtmux.constants.ResizeAdjustmentDirection` and how far to move:

```python
>>> from libtmux.constants import ResizeAdjustmentDirection

>>> # Increase height by 5 rows
>>> pane.resize(adjustment_direction=ResizeAdjustmentDirection.Up, adjustment=5)  # doctest: +ELLIPSIS
Pane(%... Window(@... ..., Session($... ...)))

>>> # Decrease width by 10 columns
>>> pane.resize(adjustment_direction=ResizeAdjustmentDirection.Left, adjustment=10)  # doctest: +ELLIPSIS
Pane(%... Window(@... ..., Session($... ...)))
```

### Zoom toggle

Zoom blows a pane up to fill the whole window so you can focus on it, then
restores the layout on the next call. It's a toggle, so the same call both
zooms and unzooms:

```python
>>> # Zoom pane to fill window
>>> pane.resize(zoom=True)  # doctest: +ELLIPSIS
Pane(%... Window(@... ..., Session($... ...)))

>>> # Unzoom
>>> pane.resize(zoom=True)  # doctest: +ELLIPSIS
Pane(%... Window(@... ..., Session($... ...)))
```

## Clearing the pane

{meth}`~libtmux.Pane.clear` wipes the pane's visible screen, leaving a clean
prompt — it runs `reset` in the pane, so it restores terminal state, not just
the screen:

```python
>>> pane.clear()  # doctest: +ELLIPSIS
Pane(%... Window(@... ..., Session($... ...)))
```

## Killing panes

{meth}`~libtmux.Pane.kill` destroys a pane and the process running inside it.
Once killed, the pane is gone from its window, and any {class}`~libtmux.Pane`
object still pointing at it is stale — drop the reference rather than reusing it.

```python
>>> # Create a temporary pane
>>> temp_pane = pane.split()
>>> temp_pane in window.panes
True

>>> # Kill it
>>> temp_pane.kill()
>>> temp_pane not in window.panes
True
```

### Kill all except current

Pass `all_except=True` to invert the target — kill every other pane in the
window and keep this one. It's the quick way to collapse a window back to a
single pane:

```python
>>> # Setup: create multiple panes
>>> pane.window.resize(height=60, width=120)  # doctest: +ELLIPSIS
Window(@... ...)

>>> keep_pane = pane.split()
>>> extra1 = pane.split()
>>> extra2 = pane.split()

>>> # Kill all except keep_pane
>>> keep_pane.kill(all_except=True)

>>> keep_pane in window.panes
True
>>> extra1 not in window.panes
True
>>> extra2 not in window.panes
True

>>> # Cleanup
>>> keep_pane.kill()
```

## Practical recipes

These tie the pieces together into the patterns you'll actually reach for:
running a command and collecting its output, and scanning output for trouble.
Lift them as-is or adapt them — both lean only on the
{meth}`~libtmux.Pane.send_keys` and {meth}`~libtmux.Pane.capture_pane` methods
you've already met.

### Recipe: run command and capture output

```python
>>> import time

>>> def run_and_capture(pane, command, marker='__DONE__', timeout=5.0):
...     """Run a command and return its output."""
...     pane.send_keys(f'{command}; echo {marker}')
...     start = time.time()
...     while time.time() - start < timeout:
...         output = pane.capture_pane()
...         output_str = '\\n'.join(output)
...         if marker in output_str:
...             return output  # Return all captured output
...         time.sleep(0.1)
...     raise TimeoutError(f'Command did not complete within {timeout}s')

>>> result = run_and_capture(pane, 'echo "captured text"', timeout=2.0)
>>> 'captured text' in '\\n'.join(result)
True
```

### Recipe: check for error patterns

```python
>>> import time

>>> def check_for_errors(pane, error_patterns=None):
...     """Check pane output for error patterns."""
...     if error_patterns is None:
...         error_patterns = ['error:', 'Error:', 'ERROR', 'failed', 'FAILED']
...     output = '\\n'.join(pane.capture_pane())
...     for pattern in error_patterns:
...         if pattern in output:
...             return True
...     return False

>>> pane.send_keys('echo "All good"')
>>> time.sleep(0.1)
>>> check_for_errors(pane)
False
```

:::{seealso}
- {ref}`api` for the full API reference
- {class}`~libtmux.Pane` for all pane methods
- {ref}`automation-patterns` for advanced orchestration patterns
:::
