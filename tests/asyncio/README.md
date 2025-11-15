# Async Tests for libtmux

This directory contains comprehensive async tests for libtmux's async API (`AsyncTmuxCmd` and `.acmd()` methods).

## 📁 Test Organization

Tests are organized by object type to mirror the sync test structure:

```
tests/asyncio/
├── test_server.py      - Server.acmd() and concurrent server operations
├── test_session.py     - Session.acmd() and concurrent session operations
├── test_window.py      - Window.acmd() and concurrent window operations
├── test_pane.py        - Pane.acmd() and concurrent pane operations
└── test_integration.py - Complex multi-object async workflows
```

## 🔒 Test Safety

**ALL tests use isolated test servers** that never affect developer tmux sessions:

- Socket names: `libtmux_test{8_random_chars}` (e.g., `libtmux_testx7k4m9n2`)
- Unique per test via `server` fixture
- Automatic cleanup via `request.addfinalizer(server.kill)`
- No manual cleanup needed (relies on pytest fixture pattern)

### Example:
```python
@pytest.mark.asyncio
async def test_my_async_feature(server: Server) -> None:
    """Test description.

    Safety: All operations in isolated test server.
    """
    result = await server.acmd("new-session", "-d", "-P", "-F#{session_id}")
    # ... test logic ...
    # No cleanup needed - fixture handles it!
```

## 🎯 Test Categories

### 1. Basic `.acmd()` Tests
Tests for low-level async command execution:
- `test_server_acmd_basic` - Basic command execution
- `test_session_acmd_basic` - Session context
- `test_window_acmd_split_pane` - Window operations
- `test_pane_acmd_send_keys` - Pane operations

### 2. Concurrent Operations
Tests showcasing async benefits (parallel execution):
- `test_concurrent_session_creation` - Create 3 sessions in parallel
- `test_concurrent_window_creation` - Create 4 windows concurrently
- `test_concurrent_pane_splits` - Create 2x2 pane grid efficiently
- `test_batch_session_operations` - Batch create and verify

### 3. Real-World Automation
Tests demonstrating practical async use cases:
- `test_batch_pane_setup_automation` - Initialize dev environment (frontend/backend/database)
- `test_concurrent_send_keys_multiple_panes` - Execute commands across panes simultaneously
- `test_parallel_pane_monitoring` - Monitor logs from multiple services
- `test_multi_session_parallel_automation` - Set up multiple project environments

### 4. Integration Workflows
Tests for complex multi-object scenarios:
- `test_async_full_workflow` - Complete workflow: session → window → pane → command
- `test_complex_pane_grid_automation` - Create 2x3 monitoring dashboard
- `test_multi_session_parallel_automation` - Automate multiple projects

### 5. Error Handling & Edge Cases
Tests for robust error handling:
- `test_async_invalid_command` - Invalid command error capture
- `test_async_session_not_found` - Nonexistent session handling
- `test_concurrent_operations_with_partial_failure` - Handle partial failures gracefully
- `test_async_command_timeout_handling` - Timeout patterns with `asyncio.wait_for()`

## 🚀 Running Tests

```bash
# Run all async tests
pytest tests/asyncio/ -v

# Run specific test file
pytest tests/asyncio/test_server.py -v

# Run specific test
pytest tests/asyncio/test_server.py::test_concurrent_session_creation -v

# Run with coverage
pytest tests/asyncio/ --cov=libtmux --cov-report=term-missing
```

## 📊 Test Statistics

| File | Tests | Focus |
|------|-------|-------|
| test_server.py | 8 | Server operations, concurrency, error handling |
| test_session.py | 4 | Session operations, parallel window management |
| test_window.py | 3 | Window operations, concurrent pane creation |
| test_pane.py | 5 | Pane operations, real-world automation |
| test_integration.py | 5 | Complex workflows, error handling |
| **Total** | **25** | **Comprehensive async coverage** |

## 💡 Key Patterns Demonstrated

### Pattern 1: Concurrent Creation
```python
@pytest.mark.asyncio
async def test_concurrent_creation(server: Server) -> None:
    """Create multiple objects concurrently."""
    async def create_session(name: str) -> Session:
        result = await server.acmd("new-session", "-d", "-P", "-F#{session_id}", "-s", name)
        return Session.from_session_id(result.stdout[0], server=server)

    # Create 3 sessions in parallel
    sessions = await asyncio.gather(
        create_session("session_1"),
        create_session("session_2"),
        create_session("session_3"),
    )
```

### Pattern 2: Parallel Queries
```python
@pytest.mark.asyncio
async def test_parallel_queries(server: Server) -> None:
    """Query multiple objects concurrently."""
    async def get_info(session_id: str) -> dict:
        result = await server.acmd("display-message", "-t", session_id, "-p", "#{session_name}")
        return {"id": session_id, "name": result.stdout[0]}

    # Query all sessions in parallel
    infos = await asyncio.gather(*[get_info(sid) for sid in session_ids])
```

### Pattern 3: Batch Automation
```python
@pytest.mark.asyncio
async def test_batch_setup(session: Session) -> None:
    """Set up multiple panes with commands."""
    configs = [
        {"cmd": "npm run dev", "name": "frontend"},
        {"cmd": "python manage.py runserver", "name": "backend"},
        {"cmd": "docker-compose up postgres", "name": "database"},
    ]

    async def setup_pane(pane_id: str, config: dict) -> bool:
        pane = Pane.from_pane_id(pane_id, server=session.server)
        await pane.acmd("send-keys", config["cmd"], "Enter")
        return True

    # Set up all panes in parallel
    await asyncio.gather(*[setup_pane(pid, cfg) for pid, cfg in zip(pane_ids, configs)])
```

### Pattern 4: Error Handling
```python
@pytest.mark.asyncio
async def test_with_error_handling(server: Server) -> None:
    """Handle errors in concurrent operations."""
    async def safe_create(name: str) -> tuple[str, bool]:
        try:
            result = await server.acmd("new-session", "-d", "-P", "-F#{session_id}", "-s", name)
            return (name, result.returncode == 0)
        except Exception:
            return (name, False)

    # Some may fail, some succeed
    results = await asyncio.gather(*[safe_create(name) for name in names])
    successes = [r for r in results if r[1]]
    failures = [r for r in results if not r[1]]
```

### Pattern 5: Timeout Handling
```python
@pytest.mark.asyncio
async def test_with_timeout(server: Server) -> None:
    """Use timeouts for async operations."""
    try:
        result = await asyncio.wait_for(
            server.acmd("new-session", "-d", "-P", "-F#{session_id}"),
            timeout=5.0
        )
    except asyncio.TimeoutError:
        # Handle timeout
        pass
```

## 🔍 Why Async Matters for tmux

Async provides **significant performance benefits** for tmux automation:

### Sequential (Sync) - 3 seconds
```python
def setup_sync(server):
    session1 = server.cmd("new-session", "-d")  # 1s
    session2 = server.cmd("new-session", "-d")  # 1s
    session3 = server.cmd("new-session", "-d")  # 1s
    # Total: 3 seconds
```

### Concurrent (Async) - 1 second
```python
async def setup_async(server):
    sessions = await asyncio.gather(
        server.acmd("new-session", "-d"),  # ┐
        server.acmd("new-session", "-d"),  # ├─ All run in parallel
        server.acmd("new-session", "-d"),  # ┘
    )
    # Total: 1 second
```

**3x faster** for this simple example. Real-world benefits increase with more operations!

## 📚 Related Documentation

- [Async API Documentation](../../docs/async_api.md) (if exists)
- [Pytest-asyncio Documentation](https://pytest-asyncio.readthedocs.io/)
- [Python asyncio Guide](https://docs.python.org/3/library/asyncio.html)

## 🤝 Contributing

When adding new async tests:

1. **Use the `server` or `session` fixture** (already isolated and safe)
2. **Decorate with `@pytest.mark.asyncio`**
3. **Add docstring with safety note**: `Safety: All operations in isolated test server.`
4. **Follow existing patterns**: Look at similar tests for examples
5. **No manual cleanup needed**: Fixtures handle it via finalizers

### Example Template:
```python
@pytest.mark.asyncio
async def test_your_feature(server: Server) -> None:
    """Test description.

    Safety: All operations in isolated test server.
    Demonstrates: [what pattern this test shows]
    """
    # Your test code
    result = await server.acmd(...)
    assert result.returncode == 0
```

## 🐛 Debugging Tips

### Test Failures
```bash
# Run with verbose output
pytest tests/asyncio/test_server.py -vv

# Run with print statements visible
pytest tests/asyncio/test_server.py -s

# Run with debug on failure
pytest tests/asyncio/test_server.py --pdb
```

### Timing Issues
If tests are flaky due to timing:
- Increase `await asyncio.sleep()` duration
- Add explicit waits after `send-keys` before `capture-pane`
- Check if panes have finished executing commands

### Isolation Issues
If tests affect each other:
- Verify using `server` fixture (not creating custom servers)
- Check socket names are unique (`libtmux_test{random}`)
- Ensure no global state between tests

---

**Questions?** Check existing tests for examples or refer to the main libtmux documentation.
