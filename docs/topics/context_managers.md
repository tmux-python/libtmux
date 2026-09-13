(context_managers)=

# Context managers

When you create tmux objects through libtmux, they normally live until you
explicitly kill them. A context manager hands that cleanup back to Python: you
scope an object to a block, and libtmux kills the underlying tmux object the
moment you leave it — whether you exit cleanly or an exception unwinds the
stack. {class}`~libtmux.Session`, {class}`~libtmux.Window`, and
{class}`~libtmux.Pane` work this way.

{class}`~libtmux.Server` is the exception, and deliberately so: it does not
kill itself on the way out unless you ask it to. A server is shared, and a
handle on one says nothing about who started it.

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
>>> import libtmux
```

## Server context manager

A {class}`~libtmux.Server` is a handle on a socket, not a connection. The same
handle addresses a daemon whether or not your process started it, and a bare
`Server()` addresses the default socket — usually the tmux you have been
working in all day. Scoping one to a block is not grounds to destroy it, so
leaving the block changes nothing:

```python
>>> already_running = Server()
>>> session = already_running.new_session(session_name='important-work')
>>> with Server(socket_name=already_running.socket_name) as scoped:
...     print(scoped.is_alive())
True
>>> print([session.session_name for session in already_running.sessions])
['important-work']
```

When teardown *is* what you want, say so with `kill_on_exit`:

```python
>>> with Server(socket_name='libtmux_doctest_ctx', kill_on_exit=True) as disposable:
...     _ = disposable.new_session()
>>> print(disposable.is_alive())
False
```

That is the one asymmetry in this page. A session, window or pane is yours by
construction — you called {meth}`~libtmux.Server.new_session` or
{meth}`~libtmux.Window.split` to get it. A server was very likely already
there.

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
once and have the layers you created torn down for you:

```python
>>> with Server() as server:
...     with server.new_session() as session:
...         with session.new_window() as window:
...             with window.split() as pane:
...                 pane.send_keys('echo "Hello"')
...                 # Do work with the pane
```

This ensures that:

1. The pane is killed when exiting its context
2. The window is killed when exiting its context
3. The session is killed when exiting its context
4. The server is left running, unless it was built with `kill_on_exit=True`

The pane, window and session tear down in reverse order (pane → window →
session), which keeps tmux's own bookkeeping consistent.

## Benefits

Reaching for a context manager buys you a few things. Sessions, windows and
panes clean themselves up the moment you leave the block, so you never manually
call {meth}`~libtmux.Session.kill`, {meth}`~libtmux.Window.kill`, or
{meth}`~libtmux.Pane.kill` and the code stays uncluttered. Because cleanup runs
on the way out of the block, it fires even when an exception unwinds the stack —
so you don't leak a stray session or pane on the error path. And when you nest
contexts, the objects tear down in hierarchical order, which keeps tmux's own
bookkeeping consistent. A server is the exception: call
{meth}`~libtmux.Server.kill` yourself, or ask for it with `kill_on_exit`.

## When to use

Use context managers when you're writing test fixtures, running short-lived
sessions, or managing several tmux servers that each need to disappear cleanly.
They also pay off in any script that might raise partway through, or when you're
spinning up an isolated environment that has to be cleaned up afterward.

[target]: http://man.openbsd.org/OpenBSD-5.9/man1/tmux.1#COMMANDS
