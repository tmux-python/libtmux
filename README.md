# libtmux: Powerful Python Control for tmux

[![Python Package](https://img.shields.io/pypi/v/libtmux.svg)](https://pypi.org/project/libtmux/)
[![Docs](https://github.com/tmux-python/libtmux/workflows/docs/badge.svg)](https://libtmux.git-pull.com/)
[![Build Status](https://github.com/tmux-python/libtmux/workflows/tests/badge.svg)](https://github.com/tmux-python/libtmux/actions?query=workflow%3A%22tests%22)
[![Code Coverage](https://codecov.io/gh/tmux-python/libtmux/branch/master/graph/badge.svg)](https://codecov.io/gh/tmux-python/libtmux)
[![License](https://img.shields.io/github/license/tmux-python/libtmux.svg)](https://github.com/tmux-python/libtmux/blob/master/LICENSE)

## What is libtmux?

**libtmux** is a fully typed Python API that provides seamless control over [tmux](https://github.com/tmux/tmux), the popular terminal multiplexer. Design your terminal workflows in clean, Pythonic code with an intuitive object-oriented interface.

## Why Use libtmux?

- 💪 **Powerful Abstractions**: Manage tmux sessions, windows, and panes through a clean object model
- 🎯 **Improved Productivity**: Automate repetitive tmux tasks with Python scripts
- 🔍 **Smart Filtering**: Find and manipulate tmux objects with Django-inspired filtering queries
- 🚀 **Versatile Applications**: Perfect for DevOps automation, development environments, and custom tooling
- 🔒 **Type Safety**: Fully typed with modern Python typing annotations for IDE autocompletion

## Quick Example

```python
import libtmux

# Connect to the tmux server
server = libtmux.Server()

# Create a development session with multiple windows
session = server.new_session(session_name="dev")

# Create organized windows for different tasks
editor = session.new_window(window_name="editor")
terminal = session.new_window(window_name="terminal")
logs = session.new_window(window_name="logs")

# Split the editor into code and preview panes
code_pane = editor.split_window(vertical=True)
preview_pane = editor.split_window(vertical=False)

# Start your development environment
code_pane.send_keys("cd ~/projects/my-app", enter=True)
code_pane.send_keys("vim .", enter=True)
preview_pane.send_keys("python -m http.server", enter=True)

# Set up terminal window for commands
terminal.send_keys("git status", enter=True)

# Start monitoring logs
logs.send_keys("tail -f /var/log/application.log", enter=True)

# Switch back to the editor window to start working
editor.select_window()
```

## Architecture: Clean Hierarchical Design

libtmux mirrors tmux's natural hierarchy with a clean object model:

```
┌─────────────────────────┐
│        Server           │ ← Connect to local or remote tmux servers
└───────────┬─────────────┘
            │
┌───────────▼─────────────┐
│        Sessions         │ ← Organize work into logical sessions
└───────────┬─────────────┘
            │
┌───────────▼─────────────┐
│        Windows          │ ← Create task-specific windows (like browser tabs)
└───────────┬─────────────┘
            │
┌───────────▼─────────────┐
│         Panes           │ ← Split windows into multiple views
└─────────────────────────┘
```

## Installation

```console
# Basic installation
$ pip install libtmux

# With development tools
$ pip install libtmux[dev]
```

## Getting Started

### 1. Create or attach to a tmux session

```console
$ tmux new-session -s my-session
```

### 2. Connect with Python

```python
import libtmux

# Connect to running tmux server
server = libtmux.Server()

# Access existing session
session = server.sessions.get(session_name="my-session")

# Or create a new one
if not session:
    session = server.new_session(session_name="my-session")
    
print(f"Connected to: {session}")
```

## Testable Examples

The following examples can be run as doctests using `py.test --doctest-modules README.md`. They assume that `server`, `session`, `window`, and `pane` objects have already been created.

### Working with Server Objects

```python
>>> # Verify server is running
>>> server.is_alive()
True

>>> # Check server has sessions attribute
>>> hasattr(server, 'sessions')
True

>>> # List all tmux sessions
>>> isinstance(server.sessions, list)
True
>>> len(server.sessions) > 0
True

>>> # At least one session should exist
>>> len([s for s in server.sessions if s.session_id]) > 0
True
```

### Session Operations

```python
>>> # Check session attributes
>>> isinstance(session.session_id, str) and session.session_id.startswith('$')
True

>>> # Verify session name exists
>>> isinstance(session.session_name, str)
True
>>> len(session.session_name) > 0
True

>>> # Session should have windows
>>> isinstance(session.windows, list)
True
>>> len(session.windows) > 0
True

>>> # Get active window
>>> session.active_window is not None
True
```

### Window Management

```python
>>> # Window has an ID
>>> isinstance(window.window_id, str) and window.window_id.startswith('@')
True

>>> # Window belongs to a session
>>> hasattr(window, 'session') and window.session is not None
True

>>> # Window has panes
>>> isinstance(window.panes, list)
True
>>> len(window.panes) > 0
True

>>> # Window has a name (could be empty but should be a string)
>>> isinstance(window.window_name, str)
True
```

### Pane Manipulation

```python
>>> # Pane has an ID
>>> isinstance(pane.pane_id, str) and pane.pane_id.startswith('%')
True

>>> # Pane belongs to a window
>>> hasattr(pane, 'window') and pane.window is not None
True

>>> # Test sending commands
>>> pane.send_keys('echo "Hello from libtmux test"', enter=True)
>>> import time
>>> time.sleep(1)  # Longer wait to ensure command execution
>>> output = pane.capture_pane()
>>> isinstance(output, list)
True
>>> len(output) > 0  # Should have some output
True
```

### Filtering Objects

```python
>>> # Session windows should be filterable
>>> windows = session.windows
>>> isinstance(windows, list)
True
>>> len(windows) > 0
True

>>> # Filter method should return a list
>>> filtered_windows = session.windows.filter()
>>> isinstance(filtered_windows, list)
True

>>> # Get method should return None or an object
>>> window_maybe = session.windows.get(window_id=window.window_id)
>>> window_maybe is None or window_maybe.window_id == window.window_id
True

>>> # Test basic filtering
>>> all(hasattr(w, 'window_id') for w in session.windows)
True
```

## Key Features

### Smart Session Management

```python
# Find sessions with powerful filtering
dev_sessions = server.sessions.filter(session_name__contains="dev")

# Create a session with context manager for auto-cleanup
with server.new_session(session_name="temp-session") as session:
    # Session will be automatically killed when exiting the context
    window = session.new_window(window_name="test")
    window.split_window().send_keys("echo 'This is a temporary workspace'", enter=True)
```

### Flexible Window Operations

```python
# Create windows programmatically
for project in ["api", "frontend", "database"]:
    window = session.new_window(window_name=project)
    window.send_keys(f"cd ~/projects/{project}", enter=True)
    
# Find windows with powerful queries
api_window = session.windows.get(window_name__exact="api")
frontend_windows = session.windows.filter(window_name__contains="front")

# Manipulate window layouts
window.select_layout("main-vertical")
```

### Precise Pane Control

```python
# Create complex layouts
main_pane = window.active_pane
side_pane = window.split_window(vertical=True, percent=30)
bottom_pane = main_pane.split_window(vertical=False, percent=20)

# Send commands to specific panes
main_pane.send_keys("vim main.py", enter=True)
side_pane.send_keys("git log", enter=True)
bottom_pane.send_keys("python -m pytest", enter=True)

# Capture and analyze output
test_output = bottom_pane.capture_pane()
if "FAILED" in "\n".join(test_output):
    print("Tests are failing!")
```

### Direct Command Access

For advanced needs, send commands directly to tmux:

```python
# Execute any tmux command directly
server.cmd("set-option", "-g", "status-style", "bg=blue")

# Access low-level command output
version_info = server.cmd("list-commands").stdout
```

## Powerful Use Cases

- **Development Environment Automation**: Script your perfect development setup
- **CI/CD Integration**: Create isolated testing environments
- **DevOps Tooling**: Manage multiple terminal sessions in server environments
- **Custom Terminal UIs**: Build terminal-based dashboards and monitoring
- **Remote Session Control**: Programmatically control remote terminal sessions

## Compatibility

- **Python**: 3.9+ (including PyPy)
- **tmux**: 1.8+ (fully tested against latest versions)

## Documentation & Resources

- [Full Documentation](https://libtmux.git-pull.com/)
- [API Reference](https://libtmux.git-pull.com/api.html)
- [Architecture Details](https://libtmux.git-pull.com/about.html)
- [Changelog](https://libtmux.git-pull.com/history.html)

## Project Information

- **Source**: [GitHub](https://github.com/tmux-python/libtmux)
- **Issues**: [GitHub Issues](https://github.com/tmux-python/libtmux/issues)
- **PyPI**: [Package](https://pypi.python.org/pypi/libtmux)
- **License**: [MIT](http://opensource.org/licenses/MIT)

## Related Projects

- [tmuxp](https://tmuxp.git-pull.com/): A tmux session manager built on libtmux
- Try `tmuxp shell` to drop into a Python shell with your current tmux session loaded

## Support Development

Your donations and contributions directly support maintenance and development of this project.

- [Support Options](https://git-pull.com/support.html)
- [Contributing Guidelines](https://libtmux.git-pull.com/contributing.html)

---

Built with ❤️ by the tmux-python team
