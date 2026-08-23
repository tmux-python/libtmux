# Detach a client

{class}`~libtmux.experimental.ops.DetachClient` disconnects one attached tmux
client without stopping its session.

## Example

This executable example uses an isolated live tmux server. `control_mode`
creates a real attached client that the example owns.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import DetachClient, ListClients, run
>>> from libtmux.experimental.ops._types import ClientName
>>> engine = SubprocessEngine.for_server(server)
>>> with control_mode() as attached:
...     client_name = attached.client_name
...     before = run(ListClients(), engine).raise_for_status()
...     result = run(
...         DetachClient(target=ClientName(client_name)),
...         engine,
...     ).raise_for_status()
...     after = run(ListClients(), engine).raise_for_status()
>>> (
...     type(result).__name__,
...     client_name in {item.name for item in before.clients},
...     client_name not in {item.name for item in after.clients},
... )
('AckResult', True, True)
```

## Operation reference

```{tmuxop:operation} detach_client
```

## Failure and effects

The target must name a currently attached client. Detaching it invalidates
snapshots that assumed the client remained connected.

## Related operations

- {tmuxop:op}`switch_client`
- {tmuxop:op}`refresh_client`
