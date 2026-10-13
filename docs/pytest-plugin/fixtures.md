---
myst:
  html_meta:
    description: "Core fixtures provided by the libtmux pytest plugin for tmux testing"
    keywords: "tmux, pytest, fixture, testing, server, session, window, pane"
---

(fixtures)=

# Fixtures

The libtmux pytest plugin provides several fixtures to help you test tmux-related functionality. These fixtures handle the setup and teardown of tmux resources automatically.

## Core fixtures

### Server fixture

```{eval-rst}
.. autofunction:: libtmux.pytest_plugin.server
```

Example usage:

```python
def test_server_functions(server):
    """Test basic server functions."""
    assert server.is_alive()
    
    # Create a new session
    session = server.new_session(session_name="test-session")
    assert session.name == "test-session"
```

### Session fixture

```{eval-rst}
.. autofunction:: libtmux.pytest_plugin.session
```

Example usage:

```python
def test_session_functions(session):
    """Test basic session functions."""
    assert session.is_alive()
    
    # Create a new window
    window = session.new_window(window_name="test-window")
    assert window.window_name == "test-window"
```

### Window fixture

```{eval-rst}
.. autofunction:: libtmux.pytest_plugin.window
```

Example usage:

```python
def test_window_functions(window):
    """Test basic window functions."""
    # Get the active pane
    pane = window.active_pane
    assert pane is not None
    
    # Split the window
    new_pane = window.split_window()
    assert len(window.panes) == 2
```

### Pane fixture

```{eval-rst}
.. autofunction:: libtmux.pytest_plugin.pane
```

Example usage:

```python
def test_pane_functions(pane):
    """Test basic pane functions."""
    # Send a command to the pane
    pane.send_keys("echo 'Hello from pane'", enter=True)
    
    # Give the command time to execute
    import time
    time.sleep(0.5)
    
    # Capture and verify the output
    output = pane.capture_pane()
    assert any("Hello from pane" in line for line in output)
```

## Helper fixtures

### TestServer fixture

```{eval-rst}
.. autofunction:: libtmux.pytest_plugin.TestServer
```

Example usage:

```python
def test_multiple_servers(TestServer):
    """Test creating multiple independent tmux servers."""
    # Create first server
    server1 = TestServer()
    session1 = server1.new_session(session_name="session1")
    
    # Create second server (completely independent)
    server2 = TestServer()
    session2 = server2.new_session(session_name="session2")
    
    # Verify both servers are running
    assert server1.is_alive()
    assert server2.is_alive()
    
    # Verify sessions exist on their respective servers only
    assert session1.server is server1
    assert session2.server is server2
```

For more advanced usage with custom configuration:

```{literalinclude} ../../tests/examples/pytest_plugin/test_direct_testserver.py
:language: python
:pyobject: test_custom_server_config
```

You can also use TestServer directly as a context manager:

```{literalinclude} ../../tests/examples/pytest_plugin/test_direct_testserver.py
:language: python
:pyobject: test_testserver_direct_usage
```

### Environment fixtures

These fixtures help manage the testing environment:

```{eval-rst}
.. autofunction:: libtmux.pytest_plugin.home_path
.. autofunction:: libtmux.pytest_plugin.user_path
.. autofunction:: libtmux.pytest_plugin.config_file
```

## Customizing fixtures

(custom_session_params)=

### Custom session parameters

You can override `session_params` to customize the `session` fixture:

```python
@pytest.fixture
def session_params():
    """Customize session parameters."""
    return {
        "x": 800,
        "y": 600,
        "suppress_history": True
    }
```

These parameters are passed directly to {meth}`Server.new_session`.

(set_home)=

### Setting a temporary home directory

You can customize the home directory used for tests:

```python
@pytest.fixture
def set_home(monkeypatch, tmp_path):
    """Set a custom temporary home directory."""
    monkeypatch.setenv("HOME", str(tmp_path))
    tmux_config = tmp_path / ".tmux.conf"
    tmux_config.write_text("set -g status off\nset -g history-limit 1000")
    return tmp_path
```

## Using a custom tmux configuration

If you need to test with a specific tmux configuration:

```python
@pytest.fixture
def custom_config(tmp_path):
    """Create a custom tmux configuration."""
    config_file = tmp_path / "tmux.conf"
    config_file.write_text("""
    set -g status off
    set -g base-index 1
    set -g history-limit 5000
    """)
    return str(config_file)

@pytest.fixture
def server_with_config(custom_config):
    """Create a server with a custom configuration."""
    server = libtmux.Server(config_file=custom_config)
    yield server
    server.kill_server()
```
