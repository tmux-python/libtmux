# libtmux

[![Python Package](https://img.shields.io/pypi/v/libtmux.svg)](https://pypi.org/project/libtmux/)
[![Docs](https://github.com/tmux-python/libtmux/workflows/docs/badge.svg)](https://libtmux.git-pull.com/)
[![Build Status](https://github.com/tmux-python/libtmux/workflows/tests/badge.svg)](https://github.com/tmux-python/libtmux/actions?query=workflow%3A%22tests%22)
[![Code Coverage](https://codecov.io/gh/tmux-python/libtmux/branch/master/graph/badge.svg)](https://codecov.io/gh/tmux-python/libtmux)
[![License](https://img.shields.io/github/license/tmux-python/libtmux.svg)](https://github.com/tmux-python/libtmux/blob/master/LICENSE)

## TL;DR

`libtmux` is a typed Python API for controlling [tmux](https://github.com/tmux/tmux), letting you programmatically manage sessions, windows, and panes with an intuitive object-oriented interface.

```python
import libtmux

# Connect to the tmux server
server = libtmux.Server()

# Create or attach to a session
session = server.new_session(session_name="my_session")

# Create a new window
window = session.new_window(window_name="my_window")

# Split the window into panes
pane1 = window.split_window(vertical=True)
pane2 = window.split_window(vertical=False)

# Send commands to panes
pane1.send_keys("echo 'Hello from pane 1'")
pane2.send_keys("ls -la", enter=True)

# Capture pane output
output = pane2.capture_pane()
```

## Overview

`libtmux` is a [typed](https://docs.python.org/3/library/typing.html) Python library that provides a wrapper for interacting programmatically with tmux, a terminal multiplexer. You can use it to manage tmux servers, sessions, windows, and panes. Additionally, `libtmux` powers [tmuxp], a tmux workspace manager.

```
┌─────────────────────────┐
│        Server           │
└───────────┬─────────────┘
            │
┌───────────▼─────────────┐
│        Sessions         │
└───────────┬─────────────┘
            │
┌───────────▼─────────────┐
│        Windows          │
└───────────┬─────────────┘
            │
┌───────────▼─────────────┐
│         Panes           │
└─────────────────────────┘
```

libtmux builds upon tmux's [target](http://man.openbsd.org/OpenBSD-5.9/man1/tmux.1#COMMANDS) and [formats](http://man.openbsd.org/OpenBSD-5.9/man1/tmux.1#FORMATS) to create an object mapping to traverse, inspect and interact with live tmux sessions.

## Installation

```console
$ pip install --user libtmux
```

## Quick Start Guide

### 1. Open a tmux session

```console
$ tmux new-session -s foo -n bar
```

### 2. Connect to your tmux session with Python

Start an interactive Python shell:

```console
$ python
```

For a better experience with autocompletions:

```console
$ pip install --user ptpython  # or ipython
$ ptpython
```

Connect to a live tmux session:

```python
>>> import libtmux
>>> server = libtmux.Server()
>>> server
Server(socket_path=/tmp/tmux-.../default)
```

**Tip**: You can also use [tmuxp]'s [`tmuxp shell`] to drop straight into your current tmux server/session/window/pane.

## Core Features

### Working with the Server

```python
# Connect with custom socket
server = libtmux.Server(socket_name='libtmux_doctest')

# Send tmux commands directly
server.cmd('display-message', 'hello world')

# Create a new session
server.cmd('new-session', '-d', '-P', '-F#{session_id}').stdout[0]  # '$2'
```

### Managing Sessions

```python
# List all sessions
server.sessions  # [Session($1 ...), Session($0 ...)]

# Filter sessions by attribute
server.sessions.filter(history_limit='2000')

# Direct lookup
server.sessions.get(session_id="$1")

# Rename a session
session = server.sessions[0]
session.rename_session('my-session')  # Session($1 my-session)
```

### Working with Windows

```python
# Create a new window (without switching to it)
bg_window = session.new_window(attach=False, window_name="background")

# Find windows by name
session.windows.filter(window_name__startswith="back")
session.windows.get(window_name__startswith="back")

# Rename a window
window = session.active_window
window.rename_window('my-project')

# Close a window
window.kill()
```

### Managing Panes

```python
# Split window to create panes
pane = window.split()  # Horizontal split (attach=True by default)
pane = window.split(attach=False)  # Don't switch to the new pane

# Select a pane
pane.select()

# Send commands to a pane
pane.send_keys('echo "Hello, world!"')
pane.send_keys('echo "No enter"', enter=False)
pane.enter()  # Press Enter key

# Clear a pane
pane.clear()

# Capture pane output
output = pane.cmd('capture-pane', '-p').stdout
print('\n'.join(output))
```

### Navigate the tmux Object Hierarchy

```python
# Traverse from pane up to session
pane.window  # Window(@1 1:..., Session($1 ...))
pane.window.session  # Session($1 ...)
```

## Compatibility

### Python Support

- Supported: Python 3.9+, pypy, pypy3
- Unsupported (no security releases or bug fixes):
  - Python 2.x: The backports branch is [`v0.8.x`](https://github.com/tmux-python/libtmux/tree/v0.8.x).

### tmux Support

- Supported: tmux 1.8+

## Documentation & Resources

- [Full Documentation](https://libtmux.git-pull.com/)
- [API Reference](https://libtmux.git-pull.com/api.html)
- [Architecture Details](https://libtmux.git-pull.com/about.html)
- [Changelog](https://libtmux.git-pull.com/history.html)

## Support Development

Your donations fund development of new features, testing and support.
Your contributions directly support maintenance and development of the project.

See donation options at <https://git-pull.com/support.html>.

## Project Information

- Source: <https://github.com/tmux-python/libtmux>
- Issues: <https://github.com/tmux-python/libtmux/issues>
- Test Coverage: <https://codecov.io/gh/tmux-python/libtmux>
- PyPI Package: <https://pypi.python.org/pypi/libtmux>
- Open Hub: <https://www.openhub.net/p/libtmux-python>
- Repology: <https://repology.org/project/python:libtmux/versions>
- License: [MIT](http://opensource.org/licenses/MIT)

[tmuxp]: https://tmuxp.git-pull.com/
[`tmuxp shell`]: https://tmuxp.git-pull.com/cli/shell.html
[ptpython]: https://github.com/prompt-toolkit/ptpython
[ipython]: https://ipython.org/
