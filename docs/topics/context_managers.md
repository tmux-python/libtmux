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

Entering a handle's context opts into destruction even if the resource already
exists. In particular, `Server()` addresses the default daemon: its context
kills all sessions on that daemon. Use {meth}`~libtmux.Server.owned` for a
private server or {meth}`~libtmux.Server.owned_session` for a session the block
creates; see {ref}`owned-context-managers` below.

Open two terminals:

Terminal one: start tmux in a separate terminal:

```console
$ tmux
```

Terminal two, `python` or `ptpython` if you have it:

```console
$ python
```

Import {class}`~libtmux.Server`:

```python
>>> from libtmux import Server
```

## Server context manager

The context kills the addressed server when you're done, including any sessions
that existed before the block:

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
...             assert pane not in window.panes
...         assert window not in session.windows
...     assert session not in server.sessions
>>> server.is_alive()
False
```

This ensures that:

1. The pane is killed when exiting its context
2. The window is killed when exiting its context
3. The session is killed when exiting its context
4. The server is killed when exiting its context

The cleanup happens in reverse order (pane → window → session → server), ensuring proper resource management.

## Cleanup after an exception

The same cleanup runs when the body raises. The exception still reaches the
caller after the context exits:

```python
>>> try:
...     with server.new_session() as temporary:
...         assert temporary in server.sessions
...         raise RuntimeError("body failed")
... except RuntimeError as error:
...     print(error)
body failed
>>> temporary in server.sessions
False
```

## Benefits

Reaching for a context manager buys you a few things. Resources clean themselves
up the moment you leave the block, so you never manually call the
{meth}`~libtmux.Server.kill`, {meth}`~libtmux.Session.kill`,
{meth}`~libtmux.Window.kill`, or {meth}`~libtmux.Pane.kill` methods and the code
stays uncluttered. Because cleanup runs on the way out of the block, it fires
even when an exception unwinds the stack — so you don't leak a stray session or
pane on the error path. And when you nest contexts, the objects tear down in
hierarchical order, which keeps tmux's own bookkeeping consistent.

(owned-context-managers)=

## Explicit ownership

Owned scopes create their resources instead of adopting an existing handle.
This makes the boundary useful when a script shares a tmux server with other
work.

### Own a private server

`Server.owned()` creates a private socket directory. The daemon starts when you
create the first session. Exiting the block kills the daemon at that private
endpoint and removes its directory, including when the body raises. This scope
never accepts an existing socket and defaults to an empty configuration.

```python
>>> from libtmux.server import Server as TmuxServer
>>> with TmuxServer.owned() as temporary:
...     created = temporary.new_session("build")
...     temporary.is_alive()
True
>>> temporary.is_alive()
False
```

The scope keeps its original cleanup endpoint if the yielded handle is
reconfigured. If cleanup fails, the exception propagates and the directory
remains available for retry. A body exception remains in the exception chain.

### Own one session

`server.owned_session()` creates a detached session on an existing server. It
rejects an existing name and cleans up only the session it created. Other
sessions remain running. Cleanup follows the session ID after a rename;
deleting the session or replacing its daemon does not transfer ownership to
another resource.

```python
>>> with server.owned_session("temporary") as created:
...     created.rename_session("renamed")
Session($... renamed)
>>> server.has_session("renamed")
False
```

Creation and cleanup use the server's command timeout. A timeout raises
{exc}`~libtmux.exc.TmuxTimeout`; the command may already have taken effect.
Cleanup errors propagate instead of being interpreted as successful removal.

### Contexts on looked-up handles

The ordinary session, window and pane contexts also kill resources obtained
through lookup. Keep those handles outside a `with` block when you intend to
leave their resources running. Here, exiting a second handle's context kills
the session created before the block:

```python
>>> created = server.new_session("lookup-context")
>>> with server.sessions.get(session_id=created.session_id) as looked_up:
...     looked_up.session_id == created.session_id
True
>>> server.has_session("lookup-context")
False
```

## When to use

Use context managers when you're writing test fixtures, running short-lived
sessions, or managing several tmux servers that each need to disappear cleanly.
They also pay off in any script that might raise partway through, or when you're
spinning up an isolated environment that has to be cleaned up afterward.

[target]: http://man.openbsd.org/OpenBSD-5.9/man1/tmux.1#COMMANDS
