# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

libtmux is a typed Python library providing an ORM-like interface for tmux (terminal multiplexer). It allows programmatic control of tmux servers, sessions, windows, and panes.

## Development Commands

### Testing
- `make test` - Run full test suite
- `make start` - Run tests then start pytest-watcher
- `make watch_test` - Auto-run tests on file changes (requires entr)
- `uv run pytest tests/path/to/specific_test.py` - Run a specific test file
- `uv run pytest -k "test_name"` - Run tests matching pattern

### Code Quality
- `make ruff` - Run linter checks (must pass before committing)
- `make ruff_format` - Auto-format code
- `make mypy` - Run type checking (must pass before committing)
- `make watch_ruff` - Auto-lint on file changes
- `make watch_mypy` - Auto-typecheck on file changes

### Documentation
- `make build_docs` - Build documentation
- `make serve_docs` - Serve docs locally at http://localhost:8009
- `make dev_docs` - Watch and rebuild docs on changes

## Architecture

### Core Objects Hierarchy
```
Server (tmux server process)
└── Session (tmux session)
    └── Window (tmux window)
        └── Pane (tmux pane)
```

Each object provides methods to:
- Query and manipulate tmux state
- Execute tmux commands
- Access child objects (e.g., server.sessions, session.windows)

### Key Modules
- `server.py` - Server class for managing tmux server
- `session.py` - Session class for tmux sessions
- `window.py` - Window class for tmux windows
- `pane.py` - Pane class for tmux panes
- `common.py` - Shared utilities and base classes
- `formats.py` - tmux format string handling
- `exc.py` - Custom exceptions

### Internal Architecture
- `_internal/dataclasses.py` - Type-safe data structures for tmux objects
- `_internal/query_list.py` - QueryList implementation for filtering collections
- All tmux commands go through `tmux_cmd()` method on objects
- Uses subprocess to communicate with tmux via CLI

### Command Execution Architecture

Commands flow through a hierarchical delegation pattern:

```
User Code → Object Method → .cmd() → Server.cmd() → tmux_cmd → subprocess → tmux binary
```

**Key components**:
- `tmux_cmd` class (`src/libtmux/common.py:193-268`) - Wraps tmux binary via subprocess
- Each object (Server, Session, Window, Pane) has a `.cmd()` method
- Commands built progressively as tuples with conditional flags
- Auto-targeting: objects automatically include their ID (`-t` flag)

**Example flow**:
```python
session.new_window(window_name='my_window', attach=False)
# → Builds: ("-d", "-P", "-F#{window_id}", "-n", "my_window")
# → Delegates: self.cmd("new-window", *args, target=self.session_id)
# → Executes: tmux -Llibtmux_test3k9m7x2q new-window -d -P -F#{window_id} -n my_window -t$1
```

### Testing Architecture

**CRITICAL: We NEVER mock tmux. All tests use real tmux processes.**

#### Core Testing Principles

1. **Real tmux processes** - Every test runs against actual tmux server via subprocess
2. **Unique isolation** - Each test gets its own tmux server with guaranteed unique socket
3. **No mocking** - All tmux commands execute through real tmux CLI
4. **Parallel-safe** - Tests can run concurrently without conflicts

#### Unique Server Isolation

Each test gets a real tmux server with unique socket name:

```python
Server(socket_name=f"libtmux_test{next(namer)}")
# Example: libtmux_test3k9m7x2q
```

**Socket name generation** (`src/libtmux/test/random.py:28-56`):
- Uses `RandomStrSequence` to generate 8-character random suffixes
- Format: `libtmux_test` + 8 random chars (lowercase, digits, underscore)
- Each socket creates independent tmux process in `/tmp/tmux-{uid}/`
- Negligible collision probability

#### Pytest Fixtures

**Fixture hierarchy** (`src/libtmux/pytest_plugin.py`):

```
Session-scoped (shared across test session):
├── home_path (temporary /home/)
├── user_path (temporary user directory)
└── config_file (~/.tmux.conf with base-index=1)

Function-scoped (per test):
├── set_home (auto-use: sets $HOME to isolated directory)
├── clear_env (cleans unnecessary environment variables)
├── server (unique tmux Server with auto-cleanup)
├── session (Session on server with unique name)
└── TestServer (factory for creating multiple servers per test)
```

**Key fixtures**:

- **`server`** - Creates tmux server with unique socket, auto-killed via finalizer
- **`session`** - Creates session on server with unique name (`libtmux_` + random)
- **`TestServer`** - Factory using `functools.partial` to create multiple independent servers
  ```python
  def test_multiple_servers(TestServer):
      server1 = TestServer()  # libtmux_test3k9m7x2q
      server2 = TestServer()  # libtmux_testz9w1b4a7
      # Both are real, independent tmux processes
  ```

#### Isolation Mechanisms

**Triple isolation ensures parallel test safety**:

1. **Unique socket names** - 8-char random suffix prevents collisions
2. **Independent processes** - Each server is separate tmux process with unique PID
3. **Isolated $HOME** - Temporary home directory with standard `.tmux.conf`

**Home directory setup**:
- Each test session gets temporary home directory
- Contains `.tmux.conf` with `base-index 1` for consistent window/pane indexing
- `$HOME` environment variable monkeypatched to isolated directory
- No interference from user's actual tmux configuration

#### Test Utilities

**Helper modules** in `src/libtmux/test/`:

- **`temporary.py`** - Context managers for temporary objects:
  ```python
  with temp_session(server) as session:
      session.new_window()  # Auto-cleaned up after block

  with temp_window(session) as window:
      window.split_window()  # Auto-cleaned up after block
  ```

- **`random.py`** - Unique name generation:
  ```python
  get_test_session_name(server)  # Returns: libtmux_3k9m7x2q (checks for uniqueness)
  get_test_window_name(session)  # Returns: libtmux_z9w1b4a7 (checks for uniqueness)
  ```

- **`retry.py`** - Retry logic for tmux operations:
  ```python
  retry_until(lambda: pane.pane_current_path is not None)
  # Retries for up to 8 seconds (configurable via RETRY_TIMEOUT_SECONDS)
  # 50ms intervals (configurable via RETRY_INTERVAL_SECONDS)
  ```

- **`constants.py`** - Test configuration:
  - `TEST_SESSION_PREFIX = "libtmux_"`
  - `RETRY_TIMEOUT_SECONDS = 8` (configurable via env var)
  - `RETRY_INTERVAL_SECONDS = 0.05` (configurable via env var)

#### Doctest Integration

**All doctests use real tmux** (`conftest.py:31-49`):

```python
@pytest.fixture(autouse=True)
def add_doctest_fixtures(doctest_namespace):
    # Injects Server, Session, Window, Pane classes
    # Injects server, session, window, pane instances
    # All are real tmux objects with unique sockets
```

Docstrings can include runnable examples:
```python
>>> server.new_session('my_session')
Session($1 my_session)

>>> session.new_window(window_name='my_window')
Window(@3 2:my_window, Session($1 ...))
```

These execute against real tmux during `pytest --doctest-modules`.

#### Parallel Test Execution

**Tests are safe for parallel execution** (`pytest -n auto`):

- Each worker process generates unique socket names
- No shared state between test workers
- Independent home directories prevent race conditions
- Automatic cleanup prevents resource leaks

#### Testing Patterns

**Standard test pattern**:
```python
def test_example(server: Server, session: Session) -> None:
    """Test description."""
    # No setup needed - fixtures provide real tmux objects
    window = session.new_window(window_name='test')
    assert window.window_name == 'test'
    # No teardown needed - fixtures auto-cleanup
```

**Multiple server pattern**:
```python
def test_multiple_servers(TestServer: t.Callable[..., Server]) -> None:
    """Test with multiple independent servers."""
    server1 = TestServer()
    server2 = TestServer()
    # Both are real tmux processes with unique sockets
    assert server1.socket_name != server2.socket_name
```

**Retry pattern for tmux operations**:
```python
def test_async_operation(session: Session) -> None:
    """Test operation that takes time to complete."""
    pane = session.active_window.active_pane
    pane.send_keys('cd /tmp', enter=True)

    # Wait for tmux to update pane path
    retry_until(lambda: pane.pane_current_path == '/tmp')
```

#### CI Testing Matrix

Tests run against:
- **tmux versions**: 2.6, 2.7, 2.8, 3.0, 3.1, 3.2, 3.3, 3.4, master
- **Python versions**: 3.9, 3.10, 3.11, 3.12, 3.13
- All use real tmux processes (never mocked)

## Important Patterns

### Command Building
- Commands built progressively as tuples with conditional flags:
  ```python
  tmux_args: tuple[str, ...] = ()

  if not attach:
      tmux_args += ("-d",)

  tmux_args += ("-P", "-F#{window_id}")

  if window_name is not None:
      tmux_args += ("-n", window_name)

  cmd = self.cmd("new-window", *tmux_args, target=target)
  ```
- Auto-targeting: objects pass their ID automatically (override with `target=`)
- Version-aware: use `has_gte_version()` / `has_lt_version()` for compatibility
- Format strings: use `FORMAT_SEPARATOR` (default `␞`) for multi-field parsing

### Type Safety
- All public APIs are fully typed
- Use `from __future__ import annotations` in all modules
- Mypy runs in strict mode - new code must be type-safe

### Error Handling
- Custom exceptions in `exc.py` (e.g., `LibTmuxException`, `TmuxCommandNotFound`)
- tmux command failures raise exceptions with command output
- Check `cmd.stderr` after command execution

### Vendor Dependencies
- Some dependencies are vendored in `_vendor/` to avoid runtime dependencies
- Do not modify vendored code directly

### Writing Tests

**When writing new tests**:
- Use `server` and `session` fixtures - they provide real tmux instances
- Never mock tmux - use `retry_until()` for async operations instead
- Use `temp_session()` / `temp_window()` context managers for temporary objects
- Use `get_test_session_name()` / `get_test_window_name()` for unique names
- Tests must work across all tmux versions (2.6+) and Python versions (3.9-3.13)
- Use version checks (`has_gte_version`, `has_lt_version`) for version-specific features

**For multiple servers per test**:
```python
def test_example(TestServer):
    server1 = TestServer()
    server2 = TestServer()
    # Both are real, independent tmux processes
```