# Suspend a client

{class}`~libtmux.experimental.ops.SuspendClient` suspends one attached client
while leaving its tmux session running.

## Example

This executable example uses the injected live `server` and `session`.
`control_mode` creates a real attached client that the example owns.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import HasSession, SuspendClient, run
>>> from libtmux.experimental.ops._types import ClientName, SessionId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> session_target = SessionId(session.session_id)
>>> with control_mode() as attached:
...     result = run(
...         SuspendClient(target=ClientName(attached.client_name)),
...         engine,
...     ).raise_for_status()
...     session_alive = run(
...         HasSession(target=session_target),
...         engine,
...     ).raise_for_status()
>>> (
...     type(result).__name__,
...     result.status,
...     result.returncode,
...     result.stdout,
...     result.stderr,
...     session_alive.exists,
... )
('AckResult', 'complete', 0, (), (), True)
```

## Operation reference

```{tmuxop:operation} suspend_client
```

## Failure and effects

Suspension leaves the tmux session alive. Depending on the tmux release,
`list-clients` may retain or filter the suspended client, so list membership is
not a portable suspension signal. Resuming terminal job control belongs to the
client process, not the operation result.

## Related operations

- {tmuxop:op}`refresh_client`
- {tmuxop:op}`switch_client`
