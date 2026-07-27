# Switch a client to another session

{class}`~libtmux.experimental.ops.SwitchClient` moves one attached client to a
different session without changing either session.

## Example

This executable example uses the injected live `server` and `session`.
`control_mode` creates a real attached client that the example owns.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListClients, NewSession, SwitchClient, run
>>> engine = SubprocessEngine.for_server(server)
>>> destination = run(
...     NewSession(session_name="docs-destination"),
...     engine,
... ).raise_for_status()
>>> assert destination.new_id is not None
>>> with control_mode() as attached:
...     before = run(ListClients(), engine).raise_for_status()
...     original = next(
...         item for item in before.clients if item.name == attached.client_name
...     )
...     result = run(
...         SwitchClient(
...             client=original.name,
...             to_session=destination.new_id,
...         ),
...         engine,
...     ).raise_for_status()
...     after = run(ListClients(), engine).raise_for_status()
...     moved = next(item for item in after.clients if item.name == original.name)
>>> (
...     type(result).__name__,
...     original.session == session.session_name,
...     moved.session == "docs-destination",
... )
('AckResult', True, True)
```

## Operation reference

```{tmuxop:operation} switch_client
```

## Failure and effects

The command identifies the client with `client` and the destination with
`to_session`; it does not use the operation's generic target field.

## Related operations

- {tmuxop:op}`suspend_client`
- {tmuxop:op}`detach_client`
