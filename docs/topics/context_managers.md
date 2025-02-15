(context_managers)=

# Context Managers

libtmux provides context managers for all main tmux objects to ensure proper cleanup of resources. This is done through Python's `with` statement, which automatically handles cleanup when you're done with the tmux objects.

Open two terminals:

Terminal one: start tmux in a separate terminal:

```console
$ tmux
```

Terminal two, `python` or `ptpython` if you have it:

```console
$ python
```

Import `libtmux`:

```python
import libtmux
```

## Server Context Manager

Create a temporary server that will be killed when you're done:

```python
>>> with Server() as server:
...     session = server.new_session()
...     print(server.is_alive())
True
>>> print(server.is_alive())  # Server is killed after exiting context
False
```

## Session Context Manager

Create a temporary session that will be killed when you're done:

```python
>>> server = Server()
>>> with server.new_session() as session:
...     print(session in server.sessions)
...     window = session.new_window()
True
>>> print(session in server.sessions)  # Session is killed after exiting context
False
```

## Window Context Manager

Create a temporary window that will be killed when you're done:

```python
>>> server = Server()
>>> session = server.new_session()
>>> with session.new_window() as window:
...     print(window in session.windows)
...     pane = window.split()
True
>>> print(window in session.windows)  # Window is killed after exiting context
False
```

## Pane Context Manager

Create a temporary pane that will be killed when you're done:

```python
>>> server = Server()
>>> session = server.new_session()
>>> window = session.new_window()
>>> with window.split() as pane:
...     print(pane in window.panes)
...     pane.send_keys('echo "Hello"')
True
>>> print(pane in window.panes)  # Pane is killed after exiting context
False
```

## Nested Context Managers

Context managers can be nested to create a clean hierarchy of tmux objects that are automatically cleaned up:

```python
>>> with Server() as server:
...     with server.new_session() as session:
...         with session.new_window() as window:
...             with window.split() as pane:
...                 pane.send_keys('echo "Hello"')
...                 # Do work with the pane
...                 # Everything is cleaned up automatically when exiting contexts
```

This ensures that:

1. The pane is killed when exiting its context
2. The window is killed when exiting its context
3. The session is killed when exiting its context
4. The server is killed when exiting its context

The cleanup happens in reverse order (pane → window → session → server), ensuring proper resource management.

## Benefits

Using context managers provides several advantages:

1. **Automatic Cleanup**: Resources are automatically cleaned up when you're done with them
2. **Clean Code**: No need to manually call `kill()` methods
3. **Exception Safety**: Resources are cleaned up even if an exception occurs
4. **Hierarchical Cleanup**: Nested contexts ensure proper cleanup order
5. **Resource Management**: Prevents resource leaks by ensuring tmux objects are properly destroyed

## When to Use

Context managers are particularly useful when:

1. Creating temporary tmux objects for testing
2. Running short-lived tmux sessions
3. Managing multiple tmux servers
4. Ensuring cleanup in scripts that may raise exceptions
5. Creating isolated environments that need to be cleaned up afterward

[target]: http://man.openbsd.org/OpenBSD-5.9/man1/tmux.1#COMMANDS
