# List attached clients and return typed snapshots

{class}`~libtmux.experimental.ops.ListClients` reads attached clients through
{class}`~libtmux.experimental.engines.subprocess.SubprocessEngine` and returns
their snapshots in
{class}`~libtmux.experimental.ops.results.ListClientsResult`.

## Example

This executable example uses an isolated live tmux server. `server`, `session`,
and `control_mode` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListClients, run
>>> engine = SubprocessEngine.for_server(server)
>>> with control_mode() as attached:
...     result = run(ListClients(), engine).raise_for_status()
...     client = next(
...         item
...         for item in result.clients
...         if item.name == attached.client_name
...     )
...     proof = (
...         type(client).__name__,
...         client.session == session.session_name,
...         client.pid is not None,
...     )
>>> proof
('ClientSnapshot', True, True)
```

## Operation reference

```{tmuxop:operation} list_clients
```

## Failure and effects

An unattached server legitimately returns no rows. The example creates an
attachment so its assertion cannot pass vacuously. Client snapshots are
point-in-time values; a client may detach after the read. The operation does not
change tmux state and is safe to repeat.

## Related operations

- {tmuxop:op}`kill_server`
- {tmuxop:op}`list_panes`
