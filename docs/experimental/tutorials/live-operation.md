# Run a live operation

{class}`~libtmux.experimental.engines.subprocess.SubprocessEngine` is the
synchronous live-server baseline. Bind it to an isolated
{class}`~libtmux.server.Server`, return a typed operation result, and leave
cleanup with the server owner. Operations stay unchanged when the engine
changes.

## Application-owned server

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
>>> type(result).__name__, result.status
('ListSessionsResult', 'complete')
>>> found
True
>>> private_server.is_alive()
False
```

## Injected-server variation

The documentation test environment injects isolated `server`, `session`,
`window`, and `pane` values. The library's pytest fixtures provide the same
style of object hierarchy. Bind the same engine with
`SubprocessEngine.for_server(server)` instead of creating another server, then
run the same operation and assert against the injected objects.

{meth}`~libtmux.experimental.engines.subprocess.SubprocessEngine.for_server`
copies the server's tmux binary and `-L` or `-S` connection arguments. It does
not transfer ownership: cleaning up the server remains the responsibility of
the context or fixture that created it.
