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

The sample windows run a plain POSIX shell so user shell initialization does not
delay their commands. Match complete output lines, and choose fresh markers when
reusing a pane so an earlier command's output cannot satisfy a later wait.

## Process control

### Starting long-running processes

When you send a command to a pane with {meth}`~libtmux.Pane.send_keys`, it runs in
the background — control returns to your script immediately, while the command keeps
going in the pane. The pane object stays your handle on that running work.

```python
>>> import time

>>> proc_window = session.new_window(window_name='process', attach=False, window_shell='sh')
>>> proc_pane = proc_window.active_pane

>>> # Start a background process
>>> proc_pane.send_keys('sleep 2 && echo "Process complete"')

>>> # The window remains available to the caller.
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
when it reaches a known state. Match whole lines and check the completion
marker first: a start marker remains in the scrollback after a command ends.
Joined captures can include right-padding spaces, including on tmux 3.2a.
These markers have no trailing spaces, so comparisons remove ASCII spaces
from each line's right edge before checking equality.

```python
>>> import time

>>> status_window = session.new_window(window_name='status-check', attach=False, window_shell='sh')
>>> status_pane = status_window.active_pane

>>> def is_process_running(pane, marker='RUNNING', completed='DONE'):
...     """Check whether output records a start without completion."""
...     lines = [line.rstrip(' ') for line in pane.capture_pane(join_wrapped=True)]
...     return completed not in lines and marker in lines

>>> is_process_running(status_pane)
False

>>> # Wait for input so the running state lasts until we release it.
>>> status_pane.send_keys(r'printf "\nRUNNING\n"; read response; printf "\nDONE\n"')

>>> deadline = time.monotonic() + 2.0
>>> while time.monotonic() < deadline:
...     if any(line.rstrip(' ') == 'RUNNING' for line in status_pane.capture_pane(join_wrapped=True)):
...         break
...     time.sleep(0.05)
>>> is_process_running(status_pane)
True

>>> # Enter releases read; the command can now print its completion marker.
>>> _ = status_pane.enter()

>>> # Wait for completion
>>> deadline = time.monotonic() + 2.0
>>> while time.monotonic() < deadline:
...     if any(line.rstrip(' ') == 'DONE' for line in status_pane.capture_pane(join_wrapped=True)):
...         break
...     time.sleep(0.05)
>>> any(line.rstrip(' ') == 'DONE' for line in status_pane.capture_pane(join_wrapped=True))
True
>>> is_process_running(status_pane)
False

>>> # Clean up
>>> status_window.kill()
```

## Output monitoring

### Waiting for specific output

Wait for a whole output line so an echoed shell command cannot satisfy the
condition before it runs. A timeout bounds the wait. The `poll_interval`
controls how often the loop calls {meth}`~libtmux.Pane.capture_pane`.

```python
>>> import time

>>> monitor_window = session.new_window(window_name='monitor', attach=False, window_shell='sh')
>>> monitor_pane = monitor_window.active_pane

>>> def wait_for_output(pane, text, timeout=5.0, poll_interval=0.1):
...     """Wait for an exact line of pane output."""
...     deadline = time.monotonic() + timeout
...     while time.monotonic() < deadline:
...         if any(line.rstrip(' ') == text for line in pane.capture_pane(join_wrapped=True)):
...             return True
...         time.sleep(poll_interval)
...     return False

>>> monitor_pane.send_keys(r'printf "\nREADY\n"', enter=False)
>>> wait_for_output(monitor_pane, 'READY', timeout=0.1)
False
>>> _ = monitor_pane.enter()
>>> wait_for_output(monitor_pane, 'READY', timeout=2.0)
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

>>> error_window = session.new_window(window_name='error-check', attach=False, window_shell='sh')
>>> error_pane = error_window.active_pane

>>> def check_for_errors(pane, patterns=None):
...     """Check pane output for error patterns."""
...     if patterns is None:
...         patterns = ['Error:', 'error:', 'ERROR', 'FAILED', 'Exception']
...     lines = pane.capture_pane(join_wrapped=True)
...     for pattern in patterns:
...         if any(line.startswith(pattern) for line in lines):
...             return pattern
...     return None

>>> # Test with successful output
>>> error_pane.send_keys(r'printf "\nSuccess!\n"')
>>> deadline = time.monotonic() + 2.0
>>> while time.monotonic() < deadline:
...     if any(line.rstrip(' ') == 'Success!' for line in error_pane.capture_pane(join_wrapped=True)):
...         break
...     time.sleep(0.05)
>>> any(line.rstrip(' ') == 'Success!' for line in error_pane.capture_pane(join_wrapped=True))
True
>>> check_for_errors(error_pane) is None
True

>>> # An error in the typed command is not output yet.
>>> error_pane.send_keys(r'printf "\nError: unavailable\n"', enter=False)
>>> check_for_errors(error_pane) is None
True
>>> _ = error_pane.enter()
>>> deadline = time.monotonic() + 2.0
>>> while time.monotonic() < deadline and check_for_errors(error_pane) is None:
...     time.sleep(0.05)
>>> check_for_errors(error_pane)
'Error:'

>>> # Clean up
>>> error_window.kill()
```

### Capturing output between markers

Bracket a command's output with distinct start and end markers. Match whole
lines so echoed command text cannot satisfy the wait. The end marker confirms
that the command has finished writing its output. The helper preserves payload
lines, including their trailing spaces; the example removes those spaces only
when displaying its result.

```python
>>> import time

>>> capture_window = session.new_window(window_name='capture', attach=False, window_shell='sh')
>>> capture_pane = capture_window.active_pane

>>> def capture_between_markers(pane, start_marker, end_marker, timeout=5.0):
...     """Capture complete output between two exact marker lines."""
...     deadline = time.monotonic() + timeout
...     while time.monotonic() < deadline:
...         lines = pane.capture_pane(join_wrapped=True)
...         markers = [line.rstrip(' ') for line in lines]
...         try:
...             start = markers.index(start_marker)
...             end = markers.index(end_marker, start + 1)
...         except ValueError:
...             time.sleep(0.05)
...             continue
...         return lines[start + 1:end]
...     return None

>>> # Test marker capture
>>> capture_pane.send_keys(
...     r'printf "\n%s\n%s\n%s\n" "BEGIN" "captured data" "END"'
... )
>>> captured = capture_between_markers(capture_pane, 'BEGIN', 'END', timeout=2.0)
>>> [line.rstrip(' ') for line in captured]
['captured data']

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

>>> parallel_window = session.new_window(window_name='parallel', attach=False, window_shell='sh')
>>> parallel_window.resize(height=40, width=120)  # doctest: +ELLIPSIS
Window(@... ...)

>>> pane1 = parallel_window.active_pane
>>> pane2 = pane1.split(direction=PaneDirection.Right, shell='sh')
>>> pane3 = pane1.split(direction=PaneDirection.Below, shell='sh')

>>> # Start tasks in parallel
>>> tasks = [
...     (pane1, r'echo "Task 1"; sleep 0.2; printf "\nDONE1\n"', 'DONE1'),
...     (pane2, r'echo "Task 2"; sleep 0.1; printf "\nDONE2\n"', 'DONE2'),
...     (pane3, r'echo "Task 3"; sleep 0.3; printf "\nDONE3\n"', 'DONE3'),
... ]

>>> for pane, cmd, marker in tasks:
...     pane.send_keys(cmd, enter=False)
>>> any(
...     any(line.rstrip(' ') == marker for line in p.capture_pane(join_wrapped=True))
...     for p, _, marker in tasks
... )
False
>>> for pane, _, _ in tasks:
...     _ = pane.enter()

>>> # Wait for all tasks
>>> deadline = time.monotonic() + 2.0
>>> while time.monotonic() < deadline:
...     if all(
...         any(line.rstrip(' ') == marker for line in p.capture_pane(join_wrapped=True))
...         for p, _, marker in tasks
...     ):
...         break
...     time.sleep(0.05)

>>> # Verify all completed
>>> all(
...     any(line.rstrip(' ') == marker for line in p.capture_pane(join_wrapped=True))
...     for p, _, marker in tasks
... )
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

>>> multi_window = session.new_window(window_name='multi-monitor', attach=False, window_shell='sh')
>>> multi_window.resize(height=40, width=120)  # doctest: +ELLIPSIS
Window(@... ...)

>>> panes = [multi_window.active_pane]
>>> panes.append(panes[0].split(direction=PaneDirection.Right, shell='sh'))
>>> panes.append(panes[0].split(direction=PaneDirection.Below, shell='sh'))

>>> def wait_all_complete(panes, marker='COMPLETE', timeout=10.0):
...     """Wait for all panes to show completion marker."""
...     deadline = time.monotonic() + timeout
...     remaining = set(range(len(panes)))
...     while remaining and time.monotonic() < deadline:
...         for i in list(remaining):
...             if any(line.rstrip(' ') == marker for line in panes[i].capture_pane(join_wrapped=True)):
...                 remaining.remove(i)
...         if remaining:
...             time.sleep(0.05)
...     return len(remaining) == 0

>>> # Start tasks with different durations
>>> for i, pane in enumerate(panes):
...     pane.send_keys(fr'sleep 0.{i+1}; printf "\nCOMPLETE\n"', enter=False)

>>> wait_all_complete(panes, 'COMPLETE', timeout=0.1)
False
>>> for pane in panes:
...     _ = pane.enter()

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
>>> with server.new_session(session_name='temp-work', window_command='sh') as temp_session:
...     window = temp_session.new_window(window_name='task', window_shell='sh')
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

>>> with session.new_window(window_name='subtask', window_shell='sh') as sub_window:
...     pane = sub_window.active_pane
...     pane.send_keys(r'printf "\nSubtask running\n"')
...     deadline = time.monotonic() + 2.0
...     while time.monotonic() < deadline:
...         if any(line.rstrip(' ') == 'Subtask running' for line in pane.capture_pane(join_wrapped=True)):
...             break
...         time.sleep(0.05)
...     any(line.rstrip(' ') == 'Subtask running' for line in pane.capture_pane(join_wrapped=True))
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
catch instead of a script that quietly stalls. A timeout stops waiting; it does
not cancel the command. This example kills its temporary window afterward.

```python
>>> import shlex
>>> import time
>>> import uuid

>>> timeout_window = session.new_window(window_name='timeout-demo', attach=False, window_shell='sh')
>>> timeout_pane = timeout_window.active_pane

>>> class CommandTimeout(Exception):
...     """Raised when a command times out."""
...     pass

>>> def run_with_timeout(pane, command, marker='__DONE__', timeout=5.0):
...     """Run command and wait for completion with timeout."""
...     marker = f'{marker}_{uuid.uuid4().hex}'
...     pane.send_keys(fr'{command}; printf "\n%s\n" {shlex.quote(marker)}')
...     deadline = time.monotonic() + timeout
...     while time.monotonic() < deadline:
...         lines = pane.capture_pane(join_wrapped=True)
...         if any(line.rstrip(' ') == marker for line in lines):
...             return '\n'.join(lines)
...         time.sleep(0.05)
...     raise CommandTimeout(f'Command timed out after {timeout}s')

>>> # Test successful command
>>> result = run_with_timeout(timeout_pane, r'printf "\nfast\n"', timeout=2.0)
>>> any(line.rstrip(' ') == 'fast' for line in result.splitlines())
True

>>> # This command waits for input; the previous marker must not complete it.
>>> try:
...     run_with_timeout(timeout_pane, 'read response', timeout=0.1)
... except CommandTimeout:
...     print('timed out')
timed out

>>> # Clean up
>>> timeout_window.kill()
```

### Retry pattern

Retry only after the preceding attempt finishes. Bracket each attempt's output
so an older success marker cannot satisfy the current attempt. The delay falls
between completed failures; a timeout returns without queuing another attempt.
The command may still be running after a timeout, until you cancel it or close
the temporary window.

```python
>>> import time
>>> import uuid

>>> retry_window = session.new_window(window_name='retry-demo', attach=False, window_shell='sh')
>>> retry_pane = retry_window.active_pane

>>> def retry_until_success(pane, command, success_marker, max_retries=3, delay=0.5, timeout=5.0):
...     """Retry command until success marker appears."""
...     for attempt in range(max_retries):
...         begin = f'__ATTEMPT_{uuid.uuid4().hex}__'
...         end = f'{begin}_END'
...         pane.send_keys(fr'printf "\n%s\n" "{begin}"; {command}; printf "\n%s\n" "{end}"')
...         deadline = time.monotonic() + timeout
...         while time.monotonic() < deadline:
...             lines = [line.rstrip(' ') for line in pane.capture_pane(start='-', join_wrapped=True)]
...             try:
...                 first = lines.index(begin)
...                 last = lines.index(end, first + 1)
...             except ValueError:
...                 time.sleep(0.05)
...                 continue
...             if success_marker in lines[first + 1:last]:
...                 return True, attempt + 1
...             break
...         else:
...             return False, attempt + 1
...         if attempt + 1 < max_retries:
...             time.sleep(delay)
...     return False, max_retries

>>> # The first attempt prints NOT OK; only the second prints the exact marker.
>>> command = (
...     'libtmux_attempt=${libtmux_attempt:-0}; libtmux_attempt=$((libtmux_attempt+1)); '
...     r'if [ "$libtmux_attempt" -ge 2 ]; then printf "\nOK\n"; else printf "\nNOT OK\n"; fi'
... )
>>> success, attempts = retry_until_success(
...     retry_pane, command, 'OK', max_retries=3, delay=0.2
... )
>>> success
True
>>> attempts
2

>>> # Clean up
>>> retry_window.kill()
```

## Agentic workflow patterns

The patterns so far drive one command at a time. The two below compose them into
longer sequences that one pane runs end to end — reach for these when a task is
genuinely a pipeline of steps, not a single call.

### Task queue processor

A task queue runs a list of commands in order, waiting for each to finish before
starting the next. You tag every task with a fresh indexed marker so you know
which step you're waiting on, and stop on the first timeout. Each result records
completion before the deadline, not the command's exit status.

```python
>>> import shlex
>>> import time
>>> import uuid

>>> queue_window = session.new_window(window_name='queue', attach=False, window_shell='sh')
>>> queue_pane = queue_window.active_pane

>>> def process_task_queue(pane, tasks, completion_marker='TASK_DONE', timeout=5.0):
...     """Process a queue of tasks sequentially."""
...     results = []
...     completion_marker = f'{completion_marker}_{uuid.uuid4().hex}'
...     for i, task in enumerate(tasks):
...         marker = f'{completion_marker}_{i}'
...         pane.send_keys(fr'{task}; printf "\n%s\n" {shlex.quote(marker)}')
...         # Wait for this task to complete
...         deadline = time.monotonic() + timeout
...         while time.monotonic() < deadline:
...             if any(line.rstrip(' ') == marker for line in pane.capture_pane(join_wrapped=True)):
...                 results.append((i, True))
...                 break
...             time.sleep(0.05)
...         else:
...             results.append((i, False))
...             break
...     return results

>>> tasks = ['echo "Step 1"', 'echo "Step 2"', 'echo "Step 3"']
>>> results = process_task_queue(queue_pane, tasks)
>>> all(success for _, success in results)
True
>>> len(results)
3

>>> # Stop before submitting a second task when the first waits for input.
>>> process_task_queue(queue_pane, ['read response', 'echo "not submitted"'], timeout=0.1)
[(0, False)]

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

>>> state_window = session.new_window(window_name='state-machine', attach=False, window_shell='sh')
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
...         deadline = time.monotonic() + timeout_per_state
...         while time.monotonic() < deadline:
...             if any(line.rstrip(' ') == next_marker for line in pane.capture_pane(join_wrapped=True)):
...                 history.append(state_name)
...                 current_state += 1
...                 break
...             time.sleep(0.05)
...         else:
...             return history, False  # Timeout
...
...     return history, True

>>> states = [
...     ('init', r'printf "\nINIT_DONE\n"', 'INIT_DONE'),
...     ('process', r'printf "\nPROCESS_DONE\n"', 'PROCESS_DONE'),
...     ('cleanup', r'printf "\nCLEANUP_DONE\n"', 'CLEANUP_DONE'),
... ]

>>> history, success = run_state_machine(state_pane, states)
>>> success
True
>>> len(history)
3

>>> blocked = [('blocked', r'read response; printf "\nUNREACHED\n"', 'UNREACHED')]
>>> run_state_machine(state_pane, blocked, timeout_per_state=0.1)
([], False)

>>> # Clean up
>>> state_window.kill()
```

## Best practices

### 1. Always use markers for completion detection

Timing is a guess; a marker is a fact. Instead of sleeping long enough and hoping a
command finished, have it print an explicit marker and poll for that. Your automation
then reacts to what actually happened rather than to a clock.

```python
>>> bp_window = session.new_window(window_name='best-practice', attach=False, window_shell='sh')
>>> bp_pane = bp_window.active_pane

>>> # Good: Use completion marker
>>> bp_pane.send_keys(r'sleep 0.1; printf "\n__DONE__\n"')

>>> # Then poll for marker
>>> import time
>>> deadline = time.monotonic() + 2.0
>>> while time.monotonic() < deadline:
...     if any(line.rstrip(' ') == '__DONE__' for line in bp_pane.capture_pane(join_wrapped=True)):
...         break
...     time.sleep(0.05)
>>> any(line.rstrip(' ') == '__DONE__' for line in bp_pane.capture_pane(join_wrapped=True))
True

>>> bp_window.kill()
```

### 2. Clean up resources

Every window and session you create lives on the tmux server until something kills
it. Tear down what you opened when you're done, so a long-running automation process
doesn't accumulate orphaned objects.

```python
>>> cleanup_window = session.new_window(window_name='cleanup-demo', attach=False, window_shell='sh')
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
>>> with session.new_window(window_name='safe-work', window_shell='sh') as safe_window:
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
