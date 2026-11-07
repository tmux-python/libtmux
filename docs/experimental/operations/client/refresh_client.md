# Refresh a client

{class}`~libtmux.experimental.ops.RefreshClient` asks tmux to redraw one
attached client and returns an acknowledgement.

## Example

This executable example uses an isolated live tmux server. `control_mode`
creates a real attached client that the example owns.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListClients, RefreshClient, run
>>> from libtmux.experimental.ops._types import ClientName
>>> engine = SubprocessEngine.for_server(server)
>>> with control_mode() as attached:
...     before = run(ListClients(), engine).raise_for_status()
...     client = next(
...         item for item in before.clients if item.name == attached.client_name
...     )
...     result = run(
...         RefreshClient(target=ClientName(client.name)),
...         engine,
...     ).raise_for_status()
...     after = run(ListClients(), engine).raise_for_status()
...     observed = next(item for item in after.clients if item.name == client.name)
...     proof = (
...         type(client).__name__,
...         type(result).__name__,
...         observed.pid == client.pid,
...     )
>>> proof
('ClientSnapshot', 'AckResult', True)
```

## Operation reference

```{tmuxop:operation} refresh_client
```

## Failure and effects

This operation changes tmux state. It is safe to repeat.

tmux exposes redraw as an acknowledgement, not a durable value that can be read
back. The example therefore proves the exact live client target and successful
typed acknowledgement without inventing a visual postcondition.

## Related operations

- {tmuxop:op}`detach_client`
- {tmuxop:op}`suspend_client`
