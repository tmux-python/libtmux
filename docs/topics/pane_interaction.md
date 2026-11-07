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

(visible-text-waits)=

## Waiting for visible text

Use {meth}`~libtmux.Pane.wait_for_text` for literal presence or absence in a
selected capture. The return value retains the satisfying text and its provenance:

```python
>>> waiting_pane = window.split(shell='sh')
>>> waiting_pane.send_keys("printf 'VISIBLE_ONLY'", enter=False)
>>> observation = waiting_pane.wait_for_text('VISIBLE_ONLY', timeout=0.5)
>>> 'VISIBLE_ONLY' in observation.text
True
>>> waiting_pane.kill()
>>> 'VISIBLE_ONLY' in observation.text
True
```

The command above was typed without Enter. Its echo satisfies the predicate;
this is evidence of visible text, not command execution or success. Text already
on screen can match the first capture, and output erased between captures can be
missed. `present=False` means absent in one selected sample:

```python
>>> empty_pane = window.split(shell='cat')
>>> observation = empty_pane.wait_for_text('missing', present=False, timeout=0.5)
>>> observation.lines
()
>>> observation.text
''
>>> empty_pane.kill()
```

### Retained evidence and failures

The immutable value exposes `pane_id`, tuple `lines`, `text`, the actual tuple
`command` argv, `start`, `end`, `join_wrapped`, and monotonic `started_ns` and
`finished_ns`. It retains no live pane/server reference and stays readable after
removal. Its `target_lifetime_verified` field is `None`: a legacy pane ID cannot
attest that the daemon or pane has not been replaced.

A deadline raises {exc}`~libtmux.exc.WaitTimeout`. Other capture failures raise
{exc}`~libtmux.exc.LibTmuxException`. Both retain `last_observation` and the
original exception in `__cause__`; failure never triggers a later diagnostic
capture. `None` means no successful sample, while an observation with empty
`text` is a successful empty capture:

```python
>>> from libtmux.exc import WaitTimeout
>>> empty_pane = window.split(shell='cat')
>>> try:
...     empty_pane.wait_for_text('missing', timeout=0)
... except WaitTimeout as error:
...     no_sample = getattr(error, 'last_observation', 'unavailable')
>>> no_sample is None
True
>>> empty_pane.kill()
```

Pass a `threading.Event` as `cancel_event` to cancel a synchronous wait. A set
event raises `concurrent.futures.CancelledError` with the same retained fields.
`KeyboardInterrupt` keeps its original identity and receives `last_observation`.
Cancellation and timeout close pipes and reap the wait's owned client; they leave
the pane program and borrowed server running. Cancelling an unrelated worker
future does not set this event.

### Bounds and scope

`timeout` is finite and nonnegative; zero expires before sampling. `interval`
is a finite sampling delay in `(0, 1]` seconds, default 0.05. Native pipe reads
check cancellation and deadline at most 0.05 seconds apart. OS scheduling and
cleanup can add latency. The adapter resolves one endpoint for the wait and
refuses custom `Pane.cmd`, `Server.cmd`, and injected engines before starting a
client, since it cannot guarantee their routing and bounds.

`max_text_codepoints` admits at most 1,048,576 decoded Unicode code points,
including joined LF; a caller may choose a smaller positive limit. The literal
must fit this limit. Raw stdout retention has a separate byte cap of four times
the configured limit plus 65,536 bytes; stderr is capped at 16,384 bytes. An
oversized capture fails without becoming a successful empty sample. These caps
bound this client's retained data, not tmux daemon memory.

The capture flags used here are available in
[tmux 3.2a](https://github.com/tmux/tmux/blob/3.2a/cmd-capture-pane.c#L38-L49).
`start`, `end`, and `join_wrapped` select the sampled text as in
{meth}`~libtmux.Pane.capture_pane`. This API supports literal matching only.
Future-only bytes, subscription readiness, gap detection, sampled quiet/stability,
regex, and process-exit status require separate contracts. Cooperative channel
signals continue to use {meth}`~libtmux.Server.wait_for`; a signal alone carries
no application exit status.

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
