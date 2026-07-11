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

Most scripts only need a couple of these patterns. Command completion and the
context manager patterns cover the common case — send a command, wait for it to
finish, clean up after yourself — so start there. The later sections (state
machines, task queues) are for the rarer cases where a single pane drives a longer
sequence of steps; reach for them when you actually need them.

When you control the command and do not need a timeout, synchronize through
{meth}`~libtmux.Server.wait_for` instead of polling the pane. When you need a
bounded wait, a retry, or output you do not control, the later patterns call
{meth}`~libtmux.Pane.capture_pane` in a loop and `sleep` between reads. Those polls
match complete output lines that cannot also occur in the shell's echoed input.
Polling costs latency — each read is a tmux round-trip, and a `sleep` between polls
is dead time you pay whether the output arrived or not.

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

Because {meth}`send_keys() <libtmux.Pane.send_keys>` doesn't wait, have the command
report its state in output lines you can distinguish from the shell's echoed input.
Capture the pane and read the most recent state after each explicit signal.

```python
>>> status_window = session.new_window(window_name='status-check', attach=False)
>>> status_pane = status_window.active_pane

>>> def latest_status(pane):
...     """Return the most recent status line."""
...     statuses = [
...         line.removeprefix('status:')
...         for line in pane.capture_pane()
...         if line.startswith('status:')
...     ]
...     return statuses[-1] if statuses else None

>>> running_channel = 'libtmux-status-running'
>>> checked_channel = 'libtmux-status-checked'
>>> done_channel = 'libtmux-status-done'
>>> status_pane.send_keys(
...     "printf 'status:%s\\n' RUNNING; "
...     f"tmux wait-for -S {running_channel}; "
...     f"tmux wait-for {checked_channel}; "
...     "sleep 0.3; printf 'status:%s\\n' DONE; "
...     f"tmux wait-for -S {done_channel}"
... )

>>> server.wait_for(running_channel)
>>> latest_status(status_pane)
'RUNNING'

>>> server.wait_for(checked_channel, set_flag=True)
>>> server.wait_for(done_channel)
>>> latest_status(status_pane)
'DONE'

>>> # Clean up
>>> status_window.kill()
```

## Output monitoring

### Waiting for command completion

When you control the command, have it signal a tmux channel after it finishes and
block on that channel with {meth}`~libtmux.Server.wait_for`. tmux remembers a signal
sent before the waiter starts, so this has no lost-wakeup race. It also avoids
confusing the shell's echoed command with the command's output.

{meth}`~libtmux.Server.wait_for` has no timeout. Make sure every expected exit path
reaches `tmux wait-for -S` so a failed command cannot leave your script blocked.
Channels are server-wide, so give each in-flight command a distinct channel name.

```python
>>> monitor_window = session.new_window(window_name='monitor', attach=False)
>>> monitor_pane = monitor_window.active_pane

>>> completion_channel = 'libtmux-automation-ready'
>>> monitor_pane.send_keys(
...     "sleep 0.2; printf 'command %s\\n' complete; "
...     f"tmux wait-for -S {completion_channel}"
... )
>>> server.wait_for(completion_channel)
>>> 'command complete' in monitor_pane.capture_pane()
True

>>> # Clean up
>>> monitor_window.kill()
```

### Detecting errors in output

Waiting for success is only half the job — you also want to notice failure. The same
capture-and-scan approach works for spotting error patterns, so you can bail out
early instead of timing out on a command that already crashed.

```python
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

>>> error_channel = 'libtmux-error-check'
>>> error_pane.send_keys(
...     "printf 'Success%s\\n' '!'; "
...     f"tmux wait-for -S {error_channel}"
... )
>>> server.wait_for(error_channel)
>>> 'Success!' in error_pane.capture_pane()
True
>>> check_for_errors(error_pane) is None
True

>>> # Clean up
>>> error_window.kill()
```

### Capturing output after completion

Sometimes you don't want to know only that a command finished — you want the lines
it produced. Wait for the completion signal before you capture the pane, then select
the result lines your command owns. Here the output values are separate shell
arguments, so neither complete result line appears in the echoed command.

```python
>>> capture_window = session.new_window(window_name='capture', attach=False)
>>> capture_pane = capture_window.active_pane

>>> capture_channel = 'libtmux-automation-capture'
>>> capture_pane.send_keys(
...     "printf 'result:%s\\n' alpha beta; "
...     f"tmux wait-for -S {capture_channel}"
... )
>>> server.wait_for(capture_channel)
>>> result = [
...     line.removeprefix('result:')
...     for line in capture_pane.capture_pane()
...     if line.startswith('result:')
... ]
>>> result
['alpha', 'beta']

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
>>> from libtmux.constants import PaneDirection

>>> parallel_window = session.new_window(window_name='parallel', attach=False)
>>> parallel_window.resize(height=40, width=120)  # doctest: +ELLIPSIS
Window(@... ...)

>>> pane1 = parallel_window.active_pane
>>> pane2 = pane1.split(direction=PaneDirection.Right)
>>> pane3 = pane1.split(direction=PaneDirection.Below)

>>> # Start tasks in parallel
>>> tasks = [
...     (pane1, '0.2', '1', 'libtmux-parallel-1'),
...     (pane2, '0.1', '2', 'libtmux-parallel-2'),
...     (pane3, '0.3', '3', 'libtmux-parallel-3'),
... ]

>>> for pane, delay, number, channel in tasks:
...     pane.send_keys(
...         f"sleep {delay}; printf 'Task %s\\n' {number}; "
...         f"tmux wait-for -S {channel}"
...     )

>>> # Wait for all tasks
>>> for _, _, _, channel in tasks:
...     server.wait_for(channel)

>>> # Verify all completed
>>> all(
...     f'Task {number}' in pane.capture_pane()
...     for pane, _, number, _ in tasks
... )
True

>>> # Clean up
>>> parallel_window.kill()
```

### Monitoring multiple panes for completion

A fixed `sleep` only works when you know how long the slowest task takes. When tasks
finish at different times, watch them all at once and drop each pane from the
watch-list as its complete output line appears. The command below assembles that
line at runtime, so the shell's echoed input cannot complete the wait.

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
...     start = time.monotonic()
...     remaining = set(range(len(panes)))
...     while remaining and time.monotonic() - start < timeout:
...         for i in list(remaining):
...             if marker in panes[i].capture_pane():
...                 remaining.remove(i)
...         time.sleep(0.1)
...     return len(remaining) == 0

>>> # Start tasks with different durations
>>> for i, pane in enumerate(panes):
...     pane.send_keys(f"sleep 0.{i+1}; printf 'COMP%s\\n' LETE")

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
>>> with session.new_window(window_name='subtask') as sub_window:
...     pane = sub_window.active_pane
...     subtask_channel = 'libtmux-subtask-complete'
...     pane.send_keys(
...         "printf 'Subtask %s\\n' running; "
...         f"tmux wait-for -S {subtask_channel}"
...     )
...     server.wait_for(subtask_channel)
...     'Subtask running' in pane.capture_pane()
True

>>> # Window cleaned up automatically
>>> sub_window not in session.windows
True
```

## Timeout handling

### Command with timeout

Any command you wait on can hang, so give every polling wait an upper bound. Append
a completion line assembled from separate shell arguments, then poll for that exact
line until it appears or the monotonic clock runs out. When it runs out, raise, so a
stuck command surfaces as an error you can catch instead of a script that quietly
stalls.

```python
>>> import shlex
>>> import time

>>> timeout_window = session.new_window(window_name='timeout-demo', attach=False)
>>> timeout_pane = timeout_window.active_pane

>>> class CommandTimeout(Exception):
...     """Raised when a command times out."""
...     pass

>>> def run_with_timeout(pane, command, marker='__DONE__', timeout=5.0):
...     """Run command and wait for completion with timeout."""
...     if len(marker) < 2:
...         raise ValueError('marker must contain at least two characters')
...     split_at = len(marker) // 2
...     marker_command = (
...         "printf '%s%s\\n' "
...         f"{shlex.quote(marker[:split_at])} "
...         f"{shlex.quote(marker[split_at:])}"
...     )
...     pane.send_keys(f'{command}; {marker_command}')
...     start = time.monotonic()
...     while time.monotonic() - start < timeout:
...         lines = pane.capture_pane()
...         if marker in lines:
...             return '\n'.join(lines)
...         time.sleep(0.1)
...     raise CommandTimeout(f'Command timed out after {timeout}s')

>>> run_with_timeout(timeout_pane, 'true', marker='x')
Traceback (most recent call last):
...
ValueError: marker must contain at least two characters

>>> # Test successful command
>>> result = run_with_timeout(timeout_pane, "printf 'fa%s\\n' st", timeout=2.0)
>>> 'fast' in result.splitlines()
True

>>> # Clean up
>>> timeout_window.kill()
```

### Retry pattern

For flaky work that succeeds on a later attempt, wait for each attempt to finish and
then look for its complete success line. A finished attempt without that line can be
retried. A timed-out attempt stops the helper: the foreground process may still own
the pane, so sending another command could feed input to the wrong process. Be
honest about the cost: `timeout_per_attempt` times `max_retries` is the worst case
you're signing up for.

```python
>>> import shlex
>>> import time

>>> retry_window = session.new_window(window_name='retry-demo', attach=False)
>>> retry_pane = retry_window.active_pane

>>> def retry_until_success(
...     pane,
...     command,
...     success_marker,
...     max_retries=3,
...     timeout_per_attempt=2.0,
...     poll_interval=0.1,
... ):
...     """Retry command until success marker appears."""
...     for attempt in range(max_retries):
...         completion_marker = f'__ATTEMPT_{attempt}_DONE__'
...         split_at = len(completion_marker) // 2
...         pane.send_keys(
...             f"{command}; printf '%s%s\\n' "
...             f"{shlex.quote(completion_marker[:split_at])} "
...             f"{shlex.quote(completion_marker[split_at:])}"
...         )
...         start = time.monotonic()
...         while time.monotonic() - start < timeout_per_attempt:
...             lines = pane.capture_pane()
...             if completion_marker in lines:
...                 if success_marker in lines:
...                     return True, attempt + 1
...                 break
...             time.sleep(poll_interval)
...         else:
...             return False, attempt + 1
...     return False, max_retries

>>> # Test retry
>>> success, attempts = retry_until_success(
...     retry_pane,
...     "printf '%s%s\\n' O K",
...     'OK',
...     max_retries=3,
...     timeout_per_attempt=2.0,
...     poll_interval=0.05,
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
starting the next. You tag every task with an indexed marker and collect a
completion/timeout result for each attempted task. On timeout the queue stops,
because the foreground process may still own the pane. Completion does not imply a
zero exit status; capture that separately when your workflow needs it.

```python
>>> import shlex
>>> import time

>>> queue_window = session.new_window(window_name='queue', attach=False)
>>> queue_pane = queue_window.active_pane

>>> def process_task_queue(pane, tasks, completion_marker='TASK_DONE'):
...     """Process a queue of tasks sequentially."""
...     results = []
...     for i, task in enumerate(tasks):
...         marker = f'{completion_marker}_{i}'
...         split_at = len(marker) // 2
...         pane.send_keys(
...             f"{task}; printf '%s%s\\n' "
...             f"{shlex.quote(marker[:split_at])} "
...             f"{shlex.quote(marker[split_at:])}"
...         )
...         # Wait for this task to complete
...         start = time.monotonic()
...         while time.monotonic() - start < 5.0:
...             if marker in pane.capture_pane():
...                 results.append((i, True))
...                 break
...             time.sleep(0.1)
...         else:
...             results.append((i, False))
...             break
...     return results

>>> tasks = ['echo "Step 1"', 'echo "Step 2"', 'echo "Step 3"']
>>> results = process_task_queue(queue_pane, tasks)
>>> all(completed for _, completed in results)
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
...         start = time.monotonic()
...         while time.monotonic() - start < timeout_per_state:
...             if next_marker in pane.capture_pane():
...                 history.append(state_name)
...                 current_state += 1
...                 break
...             time.sleep(0.1)
...         else:
...             return history, False  # Timeout
...
...     return history, True

>>> states = [
...     ('init', "printf 'INIT_%s\\n' DONE", 'INIT_DONE'),
...     ('process', "printf 'PROCESS_%s\\n' DONE", 'PROCESS_DONE'),
...     ('cleanup', "printf 'CLEANUP_%s\\n' DONE", 'CLEANUP_DONE'),
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

### 1. Use explicit completion signals

Timing is a guess; a completion signal is a fact. When you control the command and
can block without a timeout, signal a distinct tmux channel and wait on it. For a
bounded poll, match a complete output line that the echoed command cannot contain.
Both patterns react to work the shell performed rather than text it merely echoed.

```python
>>> bp_window = session.new_window(window_name='best-practice', attach=False)
>>> bp_pane = bp_window.active_pane

>>> bp_channel = 'libtmux-best-practice-complete'
>>> bp_pane.send_keys(
...     "printf 'work %s\\n' complete; "
...     f"tmux wait-for -S {bp_channel}"
... )
>>> server.wait_for(bp_channel)
>>> 'work complete' in bp_pane.capture_pane()
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
