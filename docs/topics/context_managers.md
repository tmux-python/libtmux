(context_managers)=

# Context managers

Use explicitly owned scopes for temporary tmux resources. Ordinary server,
session, window and pane handles can refer to resources created elsewhere;
obtaining a handle does not transfer ownership.

## Own a private server

{meth}`~libtmux.Server.owned` creates a private socket directory. The daemon
starts when you create the first session. Exiting the block kills the daemon
at that private endpoint and removes its directory, including when the body
raises. This scope never accepts an existing socket and defaults to an empty
configuration.

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

## Own one session

{meth}`~libtmux.Server.owned_session` creates a detached session on an existing
server. It rejects an existing name and cleans up only the session it created.
Other sessions remain running. Cleanup follows the session ID after a rename;
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
{class}`~libtmux.exc.TmuxTimeout`; the command may already have taken effect.
Cleanup errors propagate instead of being interpreted as successful removal.

## Legacy handle contexts

The existing `with Server(...)`, `with session`, `with window` and `with pane`
forms retain their destructive behavior: they kill the addressed resource on
exit even when it existed before the block. A server with no explicit socket
addresses the default daemon, so putting that handle in a context can destroy
existing interactive sessions. Use `Server.owned()` for a private server.

Lookup does not make the legacy entity contexts safe to use as borrowed
scopes. A session returned by `server.sessions.get()`, a window returned by
`session.windows.get()`, or a pane returned by `window.panes.get()` is still
killed when its context exits. Keep looked-up handles outside a `with` block
when you intend to leave their resources running.

This example deliberately creates a session before obtaining a second handle
through lookup. Exiting the lookup handle's context kills that session:

```python
>>> created = server.new_session("lookup-context")
>>> with server.sessions.get(session_id=created.session_id) as looked_up:
...     looked_up.session_id == created.session_id
True
>>> server.has_session("lookup-context")
False
```

The legacy creation patterns remain available for windows and panes:

```python
>>> with session.new_window() as temporary_window:
...     temporary_window in session.windows
True
>>> temporary_window in session.windows
False
```

```python
>>> with window.split() as temporary_pane:
...     temporary_pane in window.panes
True
>>> temporary_pane in window.panes
False
```

Nested contexts clean up in reverse order. Killing a session also affects its
windows and panes according to tmux's normal lifetime rules; closing a Python
handle alone does not terminate a tmux resource.
