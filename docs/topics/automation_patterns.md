(automation-patterns)=

# Automation Patterns

libtmux is ideal for automating terminal workflows, orchestrating multiple processes,
and building agentic systems that interact with terminal applications. This guide covers
practical patterns for automation use cases.

Open two terminals:

Terminal one: start tmux in a separate terminal:

```console
$ tmux
```

Terminal two, `python` or `ptpython` if you have it:

```console
$ python
```

## Process Control

### Starting long-running processes

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

## Output Monitoring

### Waiting for specific output

```python
>>> import time

>>> monitor_window = session.new_window(window_name='monitor', attach=False)
>>> monitor_pane = monitor_window.active_pane

>>> def wait_for_output(pane, text, timeout=5.0, poll_interval=0.1):
...     """Wait for specific text to appear in pane output."""
...     start = time.time()
...     while time.time() - start < timeout:
...         output = '\\n'.join(pane.capture_pane())
...         if text in output:
...             return True
...         time.sleep(poll_interval)
...     return False

>>> monitor_pane.send_keys('sleep 0.2; echo "READY"')
>>> wait_for_output(monitor_pane, 'READY', timeout=2.0)
True

>>> # Clean up
>>> monitor_window.kill()
```

### Detecting errors in output

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

## Multi-Pane Orchestration

### Running parallel tasks

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

## Context Manager Patterns

### Temporary session for isolated work

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

## Timeout Handling

### Command with timeout

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

## Agentic Workflow Patterns

### Task queue processor

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

## Best Practices

### 1. Always use markers for completion detection

Instead of relying on timing, use explicit markers:

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

Always clean up windows and sessions when done:

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
- {ref}`context-managers` for resource management patterns
- {class}`~libtmux.Pane` for all pane methods
:::
