(automation-patterns)=

# Automation patterns

When you automate a terminal workflow, you are usually coordinating more than one
process: you kick off work in one pane, watch another for a completion signal, and
keep several tasks moving without blocking on any single one. libtmux's object API
makes that coordination ordinary Python — you start commands with
{meth}`~libtmux.Pane.send_keys`, read what came back with
{meth}`~libtmux.Pane.capture_pane`, and fan work across panes with
{meth}`~libtmux.Pane.split`. This guide collects the patterns that turn a loose
pile of {meth}`send_keys() <libtmux.Pane.send_keys>` calls into automation you
can trust: output monitoring, timeouts, retries, and multi-pane orchestration.

Most scripts only need a couple of these patterns. Output monitoring and the
context manager patterns cover the common case — send a command, wait for a
marker, clean up after yourself — so start there. The later sections (state
machines, task queues) are for the rarer cases where a single pane drives a longer
sequence of steps; reach for them when you actually need them.

These patterns lean on polling: you call {meth}`~libtmux.Pane.capture_pane` in a
loop and `sleep` between reads. That is simpler than wiring up an event-driven
system, and it costs you latency — each poll is a tmux round-trip, and a `sleep`
between polls is dead time you pay whether the command finished or not. For most
automation that trade is worth it. When milliseconds matter, look instead at tmux
hooks or an external event-driven framework.

Open two terminals:

Terminal one: start tmux:

```console
$ tmux
```

Terminal two, `python` or `ptpython` if you have it:

```console
$ python
```

The examples below assume you already have `server` and `session` objects in scope.
In this documentation they come from libtmux's
{doc}`pytest fixtures </api/testing/pytest-plugin/fixtures>`, which run the
doctests against a live tmux server; in your own scripts you create them yourself
(a {class}`~libtmux.Server` and a session from
{meth}`~libtmux.Server.new_session`). Each example builds its own window or pane and
tears it down at the end, so the snippets stand alone and don't depend on each other.

## Process control

### Starting long-running processes

When you send a command to a pane with {meth}`~libtmux.Pane.send_keys`, it runs in
the background — control returns to your script immediately, while the command keeps
going in the pane. The pane object stays your handle on that running work.

```python
>>> import time

>>> proc_window = session.new_window(window_name='process', attach=False)
>>> proc_pane = proc_window.active_pane

>>> # Start a background process
>>> proc_pane.send_keys('sleep 2 && echo "Process complete"')

>>> # Process is running
>>> time.sleep(0.1)
>>> proc_window.window_name
'process'

>>> # Clean up
>>> proc_window.kill()
```

### Checking process status

Because {meth}`send_keys() <libtmux.Pane.send_keys>` doesn't wait, you find out
whether a command is still running the same way a person would: by reading
what's on screen. Capture the pane and look for a marker your command prints
when it reaches a known state.

```python
>>> import time

>>> status_window = session.new_window(window_name='status-check', attach=False)
>>> status_pane = status_window.active_pane

>>> def is_process_running(pane, marker='RUNNING'):
...     """Check if a marker indicates process is still running."""
...     output = pane.capture_pane()
...     return marker in '\\n'.join(output)

>>> # Start and mark a process
>>> status_pane.send_keys('echo "RUNNING"; sleep 0.3; echo "DONE"')
>>> time.sleep(0.1)

>>> # Check while running
>>> 'RUNNING' in '\\n'.join(status_pane.capture_pane())
True

>>> # Wait for completion
>>> time.sleep(0.5)
>>> 'DONE' in '\\n'.join(status_pane.capture_pane())
True

>>> # Clean up
>>> status_window.kill()
```

## Output monitoring

### Waiting for specific output

The workhorse of terminal automation is "run something, then block until a string
shows up." You wrap {meth}`~libtmux.Pane.capture_pane` in a loop with a timeout, so a
command that never finishes can't hang your script forever. The `poll_interval` is
the latency/work trade in one knob: poll faster to react sooner, slower to spare tmux
the round-trips.

> **Note:** This polls with `capture_pane` + `sleep` — correct for the
> synchronous library. If you drive tmux through the libtmux MCP server, prefer
> the event-backed `wait_for_output` tool instead: it folds live `%output` and
> returns when the pane settles, with no polling.

```python
>>> import time

>>> monitor_window = session.new_window(window_name='monitor', attach=False)
>>> monitor_pane = monitor_window.active_pane

>>> def wait_for_text(pane, text, timeout=5.0, poll_interval=0.1):
...     """Wait for specific text to appear in pane output."""
...     start = time.time()
...     while time.time() - start < timeout:
...         output = '\\n'.join(pane.capture_pane())
...         if text in output:
...             return True
...         time.sleep(poll_interval)
...     return False

>>> monitor_pane.send_keys('sleep 0.2; echo "READY"')
>>> wait_for_text(monitor_pane, 'READY', timeout=2.0)
True

>>> # Clean up
>>> monitor_window.kill()
```

### Detecting errors in output

Waiting for success is only half the job — you also want to notice failure. The same
capture-and-scan approach works for spotting error patterns, so you can bail out
early instead of timing out on a command that already crashed.

```python
>>> import time

>>> error_window = session.new_window(window_name='error-check', attach=False)
>>> error_pane = error_window.active_pane

>>> def check_for_errors(pane, patterns=None):
...     """Check pane output for error patterns."""
...     if patterns is None:
...         patterns = ['Error:', 'error:', 'ERROR', 'FAILED', 'Exception']
...     output = '\\n'.join(pane.capture_pane())
...     for pattern in patterns:
...         if pattern in output:
...             return pattern
...     return None

>>> # Test with successful output
>>> error_pane.send_keys('echo "Success!"')
>>> time.sleep(0.1)
>>> check_for_errors(error_pane) is None
True

>>> # Clean up
>>> error_window.kill()
```

### Capturing output between markers

Sometimes you don't want the whole scrollback — you want just the lines a command
produced. Bracket the interesting output with a marker you control, then return
everything that follows it. This is how you pull a command's result out of a shared
pane without dragging along the prompt and prior history.

```python
>>> import time

>>> capture_window = session.new_window(window_name='capture', attach=False)
>>> capture_pane = capture_window.active_pane

>>> def capture_after_marker(pane, marker, timeout=5.0):
...     """Capture output after a marker appears."""
...     start_time = time.time()
...     while time.time() - start_time < timeout:
...         lines = pane.capture_pane()
...         output = '\\n'.join(lines)
...         if marker in output:
...             # Return all lines after the marker
...             found = False
...             result = []
...             for line in lines:
...                 if marker in line:
...                     found = True
...                     continue
...                 if found:
...                     result.append(line)
...             return result
...         time.sleep(0.1)
...     return None

>>> # Test marker capture
>>> capture_pane.send_keys('echo "MARKER"; echo "captured data"')
>>> time.sleep(0.3)
>>> result = capture_after_marker(capture_pane, 'MARKER', timeout=2.0)
>>> any('captured' in line for line in (result or []))
True

>>> # Clean up
>>> capture_window.kill()
```

## Multi-pane orchestration

### Running parallel tasks

To run work in parallel, give each task its own pane. You split the window with
{meth}`~libtmux.Pane.split`, choosing where the new pane lands with
{class}`~libtmux.constants.PaneDirection`, then fire a command into each. Because
{meth}`send_keys() <libtmux.Pane.send_keys>` returns immediately, the tasks run
concurrently; you gather their results afterward by capturing every pane.

```python
>>> import time
>>> from libtmux.constants import PaneDirection

>>> parallel_window = session.new_window(window_name='parallel', attach=False)
>>> parallel_window.resize(height=40, width=120)  # doctest: +ELLIPSIS
Window(@... ...)

>>> pane1 = parallel_window.active_pane
>>> pane2 = pane1.split(direction=PaneDirection.Right)
>>> pane3 = pane1.split(direction=PaneDirection.Below)

>>> # Start tasks in parallel
>>> tasks = [
...     (pane1, 'echo "Task 1"; sleep 0.2; echo "DONE1"'),
...     (pane2, 'echo "Task 2"; sleep 0.1; echo "DONE2"'),
...     (pane3, 'echo "Task 3"; sleep 0.3; echo "DONE3"'),
... ]

>>> for pane, cmd in tasks:
...     pane.send_keys(cmd)

>>> # Wait for all tasks
>>> time.sleep(0.5)

>>> # Verify all completed
>>> all('DONE' in '\\n'.join(p.capture_pane()) for p, _ in tasks)
True

>>> # Clean up
>>> parallel_window.kill()
```

### Monitoring multiple panes for completion

A fixed `sleep` only works when you know how long the slowest task takes. When tasks
finish at different times, watch them all at once and drop each pane from the
watch-list as its marker appears — you return as soon as the last one completes,
instead of always waiting for a worst-case timeout.

```python
>>> import time
>>> from libtmux.constants import PaneDirection

>>> multi_window = session.new_window(window_name='multi-monitor', attach=False)
>>> multi_window.resize(height=40, width=120)  # doctest: +ELLIPSIS
Window(@... ...)

>>> panes = [multi_window.active_pane]
>>> panes.append(panes[0].split(direction=PaneDirection.Right))
>>> panes.append(panes[0].split(direction=PaneDirection.Below))

>>> def wait_all_complete(panes, marker='COMPLETE', timeout=10.0):
...     """Wait for all panes to show completion marker."""
...     start = time.time()
...     remaining = set(range(len(panes)))
...     while remaining and time.time() - start < timeout:
...         for i in list(remaining):
...             if marker in '\\n'.join(panes[i].capture_pane()):
...                 remaining.remove(i)
...         time.sleep(0.1)
...     return len(remaining) == 0

>>> # Start tasks with different durations
>>> for i, pane in enumerate(panes):
...     pane.send_keys(f'sleep 0.{i+1}; echo "COMPLETE"')

>>> # Wait for all
>>> wait_all_complete(panes, 'COMPLETE', timeout=2.0)
True

>>> # Clean up
>>> multi_window.kill()
```

## Context manager patterns

### Temporary session for isolated work

Cleanup is the part of automation that's easy to forget — and forgetting leaves
orphaned sessions and windows behind on the tmux server. A `with` block makes the
cleanup automatic: the session lives for the body and is killed on the way out, even
if an exception interrupts you. It costs a little to spin a session up and tear it
down, but you get a guaranteed-clean slate that never leaks.

```python
>>> # Create isolated session for a task
>>> with server.new_session(session_name='temp-work') as temp_session:
...     window = temp_session.new_window(window_name='task')
...     pane = window.active_pane
...     pane.send_keys('echo "Isolated work"')
...     # Session exists during work
...     temp_session in server.sessions
True

>>> # Session automatically killed after context
>>> temp_session not in server.sessions
True
```

### Temporary window for subtask

When you only need a scratch space for one subtask, scope a window the same way. The
window opens for the body of the block and is gone afterward, so a short-lived job
never outlives its purpose.

```python
>>> import time

>>> with session.new_window(window_name='subtask') as sub_window:
...     pane = sub_window.active_pane
...     pane.send_keys('echo "Subtask running"')
...     time.sleep(0.1)
...     'Subtask' in '\\n'.join(pane.capture_pane())
True

>>> # Window cleaned up automatically
>>> sub_window not in session.windows
True
```

## Timeout handling

### Command with timeout

Any command you wait on can hang, so give every wait an upper bound. Pair the command
with a completion marker and poll until either the marker shows up or the clock runs
out — and when it runs out, raise, so a stuck command surfaces as an error you can
catch instead of a script that quietly stalls.

```python
>>> import time

>>> timeout_window = session.new_window(window_name='timeout-demo', attach=False)
>>> timeout_pane = timeout_window.active_pane

>>> class CommandTimeout(Exception):
...     """Raised when a command times out."""
...     pass

>>> def run_with_timeout(pane, command, marker='__DONE__', timeout=5.0):
...     """Run command and wait for completion with timeout."""
...     pane.send_keys(f'{command}; echo {marker}')
...     start = time.time()
...     while time.time() - start < timeout:
...         output = '\\n'.join(pane.capture_pane())
...         if marker in output:
...             return output
...         time.sleep(0.1)
...     raise CommandTimeout(f'Command timed out after {timeout}s')

>>> # Test successful command
>>> result = run_with_timeout(timeout_pane, 'echo "fast"', timeout=2.0)
>>> 'fast' in result
True

>>> # Clean up
>>> timeout_window.kill()
```

### Retry pattern

For flaky work that succeeds on a later attempt, retry until a success marker
appears. Be honest about the cost: each retry runs the command again and waits the
full `delay`, so a slow `delay` times `max_retries` is the worst case you're signing
up for. Tune both for how expensive the command is and how patient you can be.

```python
>>> import time

>>> retry_window = session.new_window(window_name='retry-demo', attach=False)
>>> retry_pane = retry_window.active_pane

>>> def retry_until_success(pane, command, success_marker, max_retries=3, delay=0.5):
...     """Retry command until success marker appears."""
...     for attempt in range(max_retries):
...         pane.send_keys(command)
...         time.sleep(delay)
...         output = '\\n'.join(pane.capture_pane())
...         if success_marker in output:
...             return True, attempt + 1
...     return False, max_retries

>>> # Test retry
>>> success, attempts = retry_until_success(
...     retry_pane, 'echo "OK"', 'OK', max_retries=3, delay=0.2
... )
>>> success
True
>>> attempts
1

>>> # Clean up
>>> retry_window.kill()
```

## Agentic workflow patterns

The patterns so far drive one command at a time. The two below compose them into
longer sequences that one pane runs end to end — reach for these when a task is
genuinely a pipeline of steps, not a single call.

### Task queue processor

A task queue runs a list of commands in order, waiting for each to finish before
starting the next. You tag every task with an indexed marker so you know exactly
which step you're waiting on, and you collect a pass/fail result per task.

```python
>>> import time

>>> queue_window = session.new_window(window_name='queue', attach=False)
>>> queue_pane = queue_window.active_pane

>>> def process_task_queue(pane, tasks, completion_marker='TASK_DONE'):
...     """Process a queue of tasks sequentially."""
...     results = []
...     for i, task in enumerate(tasks):
...         pane.send_keys(f'{task}; echo "{completion_marker}_{i}"')
...         # Wait for this task to complete
...         start = time.time()
...         while time.time() - start < 5.0:
...             output = '\\n'.join(pane.capture_pane())
...             if f'{completion_marker}_{i}' in output:
...                 results.append((i, True))
...                 break
...             time.sleep(0.1)
...         else:
...             results.append((i, False))
...     return results

>>> tasks = ['echo "Step 1"', 'echo "Step 2"', 'echo "Step 3"']
>>> results = process_task_queue(queue_pane, tasks)
>>> all(success for _, success in results)
True

>>> # Clean up
>>> queue_window.kill()
```

### State machine runner

When the next step depends on the previous one finishing, model the work as a state
machine: each state runs a command and waits for the transition marker that unlocks
the next. A per-state timeout keeps a single stuck step from stalling the whole run,
and the history tells you how far you got before it stopped.

```python
>>> import time

>>> state_window = session.new_window(window_name='state-machine', attach=False)
>>> state_pane = state_window.active_pane

>>> def run_state_machine(pane, states, timeout_per_state=2.0):
...     """Run through a series of states with transitions."""
...     current_state = 0
...     history = []
...
...     while current_state < len(states):
...         state_name, command, next_marker = states[current_state]
...         pane.send_keys(command)
...
...         start = time.time()
...         while time.time() - start < timeout_per_state:
...             output = '\\n'.join(pane.capture_pane())
...             if next_marker in output:
...                 history.append(state_name)
...                 current_state += 1
...                 break
...             time.sleep(0.1)
...         else:
...             return history, False  # Timeout
...
...     return history, True

>>> states = [
...     ('init', 'echo "INIT_DONE"', 'INIT_DONE'),
...     ('process', 'echo "PROCESS_DONE"', 'PROCESS_DONE'),
...     ('cleanup', 'echo "CLEANUP_DONE"', 'CLEANUP_DONE'),
... ]

>>> history, success = run_state_machine(state_pane, states)
>>> success
True
>>> len(history)
3

>>> # Clean up
>>> state_window.kill()
```

## Best practices

### 1. Always use markers for completion detection

Timing is a guess; a marker is a fact. Instead of sleeping long enough and hoping a
command finished, have it print an explicit marker and poll for that. Your automation
then reacts to what actually happened rather than to a clock.

```python
>>> bp_window = session.new_window(window_name='best-practice', attach=False)
>>> bp_pane = bp_window.active_pane

>>> # Good: Use completion marker
>>> bp_pane.send_keys('long_command; echo "__DONE__"')

>>> # Then poll for marker
>>> import time
>>> time.sleep(0.2)
>>> '__DONE__' in '\\n'.join(bp_pane.capture_pane())
True

>>> bp_window.kill()
```

### 2. Clean up resources

Every window and session you create lives on the tmux server until something kills
it. Tear down what you opened when you're done, so a long-running automation process
doesn't accumulate orphaned objects.

```python
>>> cleanup_window = session.new_window(window_name='cleanup-demo', attach=False)
>>> cleanup_window  # doctest: +ELLIPSIS
Window(@... ...)

>>> # Do work...

>>> # Always clean up
>>> cleanup_window.kill()
>>> cleanup_window not in session.windows
True
```

### 3. Use context managers for automatic cleanup

Better still, let a `with` block do the cleanup for you. It runs even when the body
raises, which is exactly when manual cleanup tends to get skipped — so the resource
is released whether the work succeeded or blew up.

```python
>>> # Context managers ensure cleanup even on exceptions
>>> with session.new_window(window_name='safe-work') as safe_window:
...     pane = safe_window.active_pane
...     # Work happens here
...     pass  # Even if exception occurs, window is cleaned up
```

:::{seealso}
- {ref}`pane-interaction` for basic pane operations
- {ref}`workspace-setup` for creating workspace layouts
- {ref}`context_managers` for resource management patterns
- {class}`~libtmux.Pane` for all pane methods
:::
