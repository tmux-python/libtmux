# Kill the tmux server and all its sessions

{class}`~libtmux.experimental.ops.KillServer` destroys one tmux server through
{class}`~libtmux.experimental.engines.subprocess.SubprocessEngine` and returns
{class}`~libtmux.experimental.ops.results.AckResult`.

## Example

This executable example creates and owns a second live tmux server so the
documentation fixture remains intact.

```python
>>> import uuid
>>> from libtmux.server import Server
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import KillServer, run
>>> socket_name = f"libtmux-doc-{uuid.uuid4().hex}"
>>> with Server(socket_name=socket_name) as doomed:
...     _ = doomed.new_session(session_name="docs-doomed")
...     before = doomed.is_alive()
...     result = run(
...         KillServer(),
...         SubprocessEngine.for_server(doomed),
...     ).raise_for_status()
...     proof = before, type(result).__name__, doomed.is_alive()
>>> proof
(True, 'AckResult', False)
```

## Operation reference

```{tmuxop:operation} kill_server
```

## Failure and effects

This operation ends every session on its target server and cannot be undone.
The example creates and destroys a second server, leaving the primary
documentation server intact. A later operation through the dead server's
engine fails because no server remains.

## Related operations

- {tmuxop:op}`delete_buffer`
- {tmuxop:op}`list_clients`
