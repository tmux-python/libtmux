# Suspend a client

{class}`~libtmux.experimental.ops.SuspendClient` suspends one attached client
while leaving its tmux session running.

## Example

This executable example uses the injected live `server` and `session`.
`control_mode` creates a real attached client that the example owns.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import HasSession, ListClients, SuspendClient, run
>>> from libtmux.experimental.ops._types import ClientName, SessionId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> session_target = SessionId(session.session_id)
>>> with control_mode() as attached:
...     client_name = attached.client_name
...     before = run(ListClients(), engine).raise_for_status()
...     client = next(item for item in before.clients if item.name == client_name)
...     result = run(
...         SuspendClient(target=ClientName(client.name)),
...         engine,
...     ).raise_for_status()
...     after = run(ListClients(), engine).raise_for_status()
...     session_alive = run(HasSession(target=session_target), engine)
>>> (
...     type(client).__name__,
...     type(result).__name__,
...     client_name not in {item.name for item in after.clients},
...     type(session_alive).__name__,
...     session_alive.exists,
... )
('ClientSnapshot', 'AckResult', True, 'HasSessionResult', True)
```

## Operation reference

```{tmuxop:operation} suspend_client
```

## Failure and effects

Suspension removes the client from the active client listing but leaves its
session alive. Resuming terminal job control belongs to the client process, not
the operation result.

## Related operations

- {tmuxop:op}`refresh_client`
- {tmuxop:op}`switch_client`
