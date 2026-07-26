# Async control-mode engine

{class}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine`
combines hybrid async dispatch with supervised control-mode reconnection and
notification fan-out.

## Use it when

Use it for async command batches, desired subscription replay across
reconnections, or consumers of raw control-mode notifications.

## Avoid it when

Choose async subprocess execution when each request should have an independent
child lifetime. Do not choose this engine on the assumption that notification
subscription has a public readiness handshake.

## Construction and cleanup

Bind the engine with
{meth}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine.for_server`.
Use the async context manager or call
{meth}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine.aclose`.

Async context entry looks for an existing session whose effective
`destroy-unattached` value is `off`. When it finds one, it starts the
supervisor eagerly and attaches to that exact session ID with
`attach-session -E`; tmux neither chooses a different session nor applies
`update-environment`. If no safe session exists, context entry stays lazy and
the first batch uses
{class}`~libtmux.experimental.engines.asyncio.AsyncSubprocessEngine`. This lets
`new-session` bootstrap an empty server without creating a private control
session. A later batch can open the persistent connection.

```python
>>> import asyncio
>>> from libtmux.experimental.engines import AsyncControlModeEngine, CommandRequest
>>> assert session.session_id is not None
>>> assert window.window_id is not None
>>> requests = [
...     CommandRequest.from_args(
...         "display-message", "-p", "-t", session.session_id, "#{session_id}"
...     ),
...     CommandRequest.from_args(
...         "display-message", "-p", "-t", window.window_id, "#{window_id}"
...     ),
... ]
>>> async def query_targets():
...     async with AsyncControlModeEngine.for_server(server) as engine:
...         return await engine.run_batch(requests)
>>> results = asyncio.run(query_targets())
>>> [result.returncode for result in results]
[0, 0]
>>> results[0].stdout == (session.session_id,)
True
>>> results[1].stdout == (window.window_id,)
True
```

## Lifecycle and failure boundary

A supervisor owns the connection, reader, reconnection backoff, and replay of
state registered with
{meth}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine.add_subscription`
and
{meth}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine.set_attach_targets`.
Per-subscriber queues are bounded;
{attr}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine.dropped_notifications`
reports overflow. Connection failures and timeouts raise at the engine
boundary, while tmux command errors remain result data. Sequence anomalies are
logged.

The persistent process has normal tmux client semantics: `list-clients` shows
it, `session_attached` includes it, and client attach and detach hooks can
observe it. The engine never changes `destroy-unattached` and does not issue a
session-deletion command during cleanup. If that option changes while the
client is attached, closing the engine detaches normally and tmux applies the
new policy.

{meth}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine.subscribe`
is an async generator. Its queue is registered only when iteration advances,
not when the generator object is created, and it does not start the engine.
If context entry stayed lazy, or the caller does not use the context manager, a
notification-only consumer must call
{meth}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine.start`
after a safe session exists; direct startup raises
{exc}`~libtmux.experimental.engines.control_mode.ControlModeError` when none is
available. The API has no subscriber-readiness signal, so code must not assume
a notification emitted before the first iteration will be delivered.

## API

```{eval-rst}
.. autoclass:: libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine
   :members:
   :special-members: __aenter__, __aexit__
```

## Related tutorials

See {doc}`../tutorials/control-mode` for the shared batching contract and the
notification boundary. See {doc}`../tutorials/async-control-plans` to compose
forward-referenced operations and fold them into control-mode dispatches.
