# Run a live operation

A live example needs an isolated {class}`~libtmux.server.Server`, an engine
bound to that server, and explicit cleanup. Operations stay unchanged when the
engine changes.

## Standalone setup

Use the public server context manager when the calling application owns tmux
setup. A unique socket name isolates the example from the user's normal server;
context exit kills the private server.

```python
>>> import uuid
>>> from libtmux.server import Server as TmuxServer
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListSessions, run
>>> socket_name = f"libtmux-doc-{uuid.uuid4().hex}"
>>> with TmuxServer(socket_name=socket_name) as private_server:
...     private_session = private_server.new_session(session_name="docs-live")
...     engine = SubprocessEngine.for_server(private_server)
...     result = run(ListSessions(), engine).raise_for_status()
...     found = any(
...         item.session_id == private_session.session_id
...         for item in result.sessions
...     )
>>> found
True
>>> private_server.is_alive()
False
```

## Documentation and test setup

The documentation test environment injects isolated `server`, `session`,
`window`, and `pane` values. The library's pytest fixtures provide the same
style of object hierarchy, so tests can bind an engine without repeating server
creation.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListSessions, run
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> result = run(ListSessions(), engine).raise_for_status()
>>> any(item.session_id == session.session_id for item in result.sessions)
True
```

{meth}`~libtmux.experimental.engines.subprocess.SubprocessEngine.for_server`
copies the server's tmux binary and `-L` or `-S` connection arguments. It does
not transfer ownership: cleaning up the server remains the responsibility of
the context or fixture that created it.
