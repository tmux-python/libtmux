(pane-interaction)=

# Pane Interaction

libtmux provides powerful methods for interacting with tmux panes programmatically.
This is especially useful for automation, testing, and orchestrating terminal-based
workflows.

Open two terminals:

Terminal one: start tmux in a separate terminal:

```console
$ tmux
```

Terminal two, `python` or `ptpython` if you have it:

```console
$ python
```

## Sending Commands

The {meth}`~libtmux.Pane.send_keys` method sends text to a pane, optionally pressing
Enter to execute it.

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

Use `enter=False` to type text without executing:

```python
>>> pane.send_keys('echo "waiting"', enter=False)

>>> # Text is typed but not executed
>>> output = pane.capture_pane()
>>> 'waiting' in '\\n'.join(output)
True
```

Press Enter separately with {meth}`~libtmux.Pane.enter`:

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

Use `literal=True` to send special characters without interpretation:

```python
>>> import time

>>> pane.send_keys('echo "Tab:\\tNewline:\\n"', literal=True)

>>> time.sleep(0.1)
```

### Suppress shell history

Use `suppress_history=True` to prepend a space (prevents command from being
saved in shell history):

```python
>>> import time

>>> pane.send_keys('echo "secret command"', suppress_history=True)

>>> time.sleep(0.1)
```

## Capturing Output

The {meth}`~libtmux.Pane.capture_pane` method captures text from a pane's buffer.

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

Capture specific line ranges using `start` and `end` parameters:

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

Capture colored output with escape sequences preserved using `escape_sequences=True`:

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

Long lines that wrap in the terminal can be joined back together:

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

| Parameter | tmux Flag | Description |
|-----------|-----------|-------------|
| `escape_sequences` | `-e` | Include ANSI escape sequences (colors, attributes) |
| `escape_non_printable` | `-C` | Escape non-printable chars as octal `\xxx` |
| `join_wrapped` | `-J` | Join wrapped lines back together |
| `preserve_trailing` | `-N` | Preserve trailing spaces at line ends |
| `trim_trailing` | `-T` | Trim trailing empty positions (tmux 3.4+) |

:::{note}
The `trim_trailing` parameter requires tmux 3.4+. If used with an older version,
a warning is issued and the flag is ignored.
:::

## Waiting for Output

A common pattern in automation is waiting for a command to complete.

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

## Querying Pane State

The {meth}`~libtmux.Pane.display_message` method queries tmux format variables.

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

| Variable | Description |
|----------|-------------|
| `#{pane_width}` | Pane width in characters |
| `#{pane_height}` | Pane height in characters |
| `#{pane_current_path}` | Current working directory |
| `#{pane_pid}` | PID of the pane's shell |
| `#{pane_id}` | Unique pane ID (e.g., `%0`) |
| `#{pane_index}` | Pane index in window |

## Resizing Panes

The {meth}`~libtmux.Pane.resize` method adjusts pane dimensions.

### Resize by specific dimensions

```python
>>> # Make pane larger
>>> pane.resize(height=20, width=80)  # doctest: +ELLIPSIS
Pane(%... Window(@... ..., Session($... ...)))
```

### Resize by adjustment

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

```python
>>> # Zoom pane to fill window
>>> pane.resize(zoom=True)  # doctest: +ELLIPSIS
Pane(%... Window(@... ..., Session($... ...)))

>>> # Unzoom
>>> pane.resize(zoom=True)  # doctest: +ELLIPSIS
Pane(%... Window(@... ..., Session($... ...)))
```

## Clearing the Pane

The {meth}`~libtmux.Pane.clear` method clears the pane's screen:

```python
>>> pane.clear()  # doctest: +ELLIPSIS
Pane(%... Window(@... ..., Session($... ...)))
```

## Killing Panes

The {meth}`~libtmux.Pane.kill` method destroys a pane:

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

## Practical Recipes

### Recipe: Run command and capture output

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

### Recipe: Check for error patterns

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
