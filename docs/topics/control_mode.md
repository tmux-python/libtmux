# Control Mode Engine

The control mode engine provides a high-performance alternative to the default subprocess-based command execution. By maintaining a persistent connection to the tmux server, control mode eliminates the overhead of spawning a new process for each command.

## Overview

libtmux offers two command execution engines:

1. **Subprocess Engine** (default): Spawns a new tmux process for each command
2. **Control Mode Engine**: Uses a persistent tmux control mode connection

The control mode engine is particularly beneficial for:
- Scripts with many sequential tmux operations
- Query-heavy workloads (list sessions, windows, panes)
- Performance-critical applications

## Performance Characteristics

Control mode provides significant performance improvements for sequential operations:

- **Query operations**: 10-50x faster (e.g., `list-sessions`, `list-windows`)
- **Mixed workloads**: 5-15x faster (creation + queries)
- **Single operations**: Similar performance to subprocess

The speedup comes from eliminating process spawn overhead. Each subprocess call incurs ~5-10ms of overhead, while control mode operations complete in microseconds.

See `tests/control_mode/test_benchmarks.py` for detailed performance comparisons.

## Usage

### Basic Usage

```python
from libtmux._internal.engines import ControlModeCommandRunner
from libtmux.server import Server

# Create control mode runner
runner = ControlModeCommandRunner("my_socket")

# Create server with control mode
server = Server(socket_name="my_socket", command_runner=runner)

# All operations now use persistent connection
session = server.new_session("my_session")
window = session.new_window("my_window")

# Query operations are very fast
sessions = server.sessions
windows = session.windows

# Cleanup when done
runner.close()
```

### Context Manager

The recommended pattern uses a context manager for automatic cleanup:

```python
from libtmux._internal.engines import ControlModeCommandRunner
from libtmux.server import Server

with ControlModeCommandRunner("my_socket") as runner:
    server = Server(socket_name="my_socket", command_runner=runner)

    # Perform many operations
    for i in range(100):
        session = server.new_session(f"session_{i}")
        session.new_window(f"window_{i}")

    # Query operations
    all_sessions = server.sessions

# Connection automatically closed on exit
```

## Transparent Subprocess Fallback

Control mode doesn't support tmux format strings (`-F` flag). Operations that require format strings transparently fall back to subprocess execution:

```python
with ControlModeCommandRunner("my_socket") as runner:
    server = Server(socket_name="my_socket", command_runner=runner)

    # This uses control mode (fast)
    sessions = server.sessions

    # This transparently uses subprocess (format string required)
    session = server.new_session("my_session")  # Uses -F#{session_id}

    # This uses control mode again (fast)
    windows = session.windows
```

This fallback is:
- **Automatic**: No code changes required
- **Transparent**: Same interface, same behavior
- **Optimal**: 80-90% of operations still use control mode

### Operations That Use Subprocess Fallback

The following operations require format strings and use subprocess:
- `Server.new_session()` - needs session ID
- `Session.new_window()` - needs window ID
- `Pane.split()` - needs pane ID

All other operations (queries, modifications, etc.) use control mode.

## Thread Safety

Control mode runner is thread-safe but serializes command execution:

```python
import threading

with ControlModeCommandRunner("my_socket") as runner:
    server = Server(socket_name="my_socket", command_runner=runner)

    def create_sessions(start_idx: int) -> None:
        for i in range(start_idx, start_idx + 10):
            server.new_session(f"thread_session_{i}")

    # Multiple threads can safely use the same runner
    threads = [
        threading.Thread(target=create_sessions, args=(i * 10,))
        for i in range(5)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
```

Commands are executed sequentially (one at a time) even when called from multiple threads. This ensures correct tmux state and prevents output parsing errors.

## Implementation Details

### Architecture

Control mode works by:

1. Starting tmux with `-C` flag (control mode)
2. Sending commands over stdin
3. Parsing structured output from stdout
4. Queuing notifications for later processing

The protocol uses `%begin`, `%end`, and `%error` blocks:

```
%begin 1234 1
session_name: 2 windows (created ...)
%end 1234 1
```

### Connection Lifecycle

```python
# Connection established on initialization
runner = ControlModeCommandRunner("my_socket")
# tmux -C -L my_socket started in background

# Commands use persistent connection
result = runner.run("list-sessions")

# Explicit cleanup
runner.close()
# Background process terminated
```

### Error Handling

Control mode handles errors gracefully:

```python
result = runner.run("invalid-command")
assert result.returncode == 1
assert "unknown command" in result.stdout[0].lower()
```

Errors are returned as `ControlModeResult` with non-zero return code, matching subprocess behavior.

## When to Use Control Mode

**Use control mode when:**
- Running many tmux commands sequentially
- Performance is critical
- Querying tmux state frequently

**Use subprocess (default) when:**
- Running single/few commands
- Simplicity is preferred over performance
- No need for connection management

**Example: Script with 100 operations**

```python
# Subprocess: ~500ms-1000ms (5-10ms per operation)
server = Server(socket_name="my_socket")
for i in range(100):
    sessions = server.sessions  # 100 subprocess spawns

# Control mode: ~50ms-100ms (0.5-1ms per operation)
with ControlModeCommandRunner("my_socket") as runner:
    server = Server(socket_name="my_socket", command_runner=runner)
    for i in range(100):
        sessions = server.sessions  # 100 control mode queries
```

## Limitations

1. **Format strings not supported**: Operations with `-F` flag use subprocess fallback
2. **Single connection**: One control mode connection per socket (thread-safe but serialized)
3. **Connection management**: Requires explicit `close()` or context manager

## See Also

- {doc}`/api/index` - API reference for Server, Session, Window, Pane
- `tests/control_mode/` - Implementation tests (all use real tmux)
- `tests/control_mode/test_benchmarks.py` - Performance benchmarks
