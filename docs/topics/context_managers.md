(context_managers)=

# Context managers

When you create tmux objects through libtmux, they normally live until you
explicitly kill them. A context manager hands that cleanup back to Python: you
scope an object to a block, and libtmux kills the underlying tmux object the
moment you leave it — whether you exit cleanly or an exception unwinds the
stack. The {class}`~libtmux.Server`, {class}`~libtmux.Session`,
{class}`~libtmux.Window`, and {class}`~libtmux.Pane` classes (all main tmux
objects) support this.

Most readers never reach for this. If you're building a long-running
application, you typically let objects persist and tear them down yourself. The
context-manager form earns its keep in test fixtures and short-lived scripts,
where you want a tmux object to exist for exactly one block and then vanish.

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

## Server context manager

You create a temporary server that will be killed when you're done:

```python
>>> with Server() as server:
...     session = server.new_session()
...     print(server.is_alive())
True
>>> print(server.is_alive())  # Server is killed after exiting context
False
```

## Session context manager

You create a temporary session that will be killed when you're done:

```python
>>> server = Server()
>>> with server.new_session() as session:
...     print(session in server.sessions)
...     window = session.new_window()
True
>>> print(session in server.sessions)  # Session is killed after exiting context
False
```

## Window context manager

You create a temporary window that will be killed when you're done:

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

## Pane context manager

You create a temporary pane that will be killed when you're done:

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

## Nested context managers

For complex setups, you can nest contexts to build a whole tmux hierarchy at
once and have every layer torn down for you:

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

Reaching for a context manager buys you a few things. Resources clean themselves
up the moment you leave the block, so you never manually call the
{meth}`~libtmux.Server.kill`, {meth}`~libtmux.Session.kill`,
{meth}`~libtmux.Window.kill`, or {meth}`~libtmux.Pane.kill` methods and the code
stays uncluttered. Because cleanup runs on the way out of the block, it fires
even when an exception unwinds the stack — so you don't leak a stray session or
pane on the error path. And when you nest contexts, the objects tear down in
hierarchical order, which keeps tmux's own bookkeeping consistent.

## When to use

Use context managers when you're writing test fixtures, running short-lived
sessions, or managing several tmux servers that each need to disappear cleanly.
They also pay off in any script that might raise partway through, or when you're
spinning up an isolated environment that has to be cleaned up afterward.

[target]: http://man.openbsd.org/OpenBSD-5.9/man1/tmux.1#COMMANDS
