# Use control mode

Once connected, control-mode engines keep one `tmux -C` client alive and
correlate tmux's framed replies with submitted
{class}`~libtmux.experimental.engines.base.CommandRequest` values.
Over that connected client,
{meth}`~libtmux.experimental.engines.control_mode.ControlModeEngine.run_batch`
and
{meth}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine.run_batch`
pipeline commands instead of starting one process per request.

## How attachment stays safe

Before opening a control connection, the engine looks for an existing session
whose effective `destroy-unattached` value is `off`. It attaches to that exact
session ID with `attach-session -E`. The exact target avoids tmux's implicit
session selection, while `-E` leaves the session's `update-environment` state
unchanged.

If no safe session exists, the engine uses the corresponding subprocess engine
for that batch. `new-session` can therefore bootstrap an empty server without a
private control session. A later batch can switch to the persistent client once
a safe session exists.

The control process is still a normal attached client. It appears in
`list-clients`, contributes to `session_attached`, and participates in client
attach and detach hooks. The engine does not change `destroy-unattached` or
issue a session-deletion command during cleanup. If you change that option
while the engine is connected, tmux applies the new policy when the client
detaches.

## Synchronous batch

Use {class}`~libtmux.experimental.engines.control_mode.ControlModeEngine` as a
context manager so the persistent control client is closed on every exit path.
Context entry is lazy; the first batch chooses persistent or subprocess
dispatch.

```python
>>> from libtmux.experimental.engines import CommandRequest, ControlModeEngine
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
>>> with ControlModeEngine.for_server(server) as engine:
...     results = engine.run_batch(requests)
>>> [result.stdout[0] for result in results] == [
...     session.session_id,
...     window.window_id,
... ]
True
```

## Async batch

The async context scopes and closes
{class}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine`.
When a safe session already exists, context entry eagerly starts its supervisor
so notification consumers have a reader without first sending a command. On an
empty server, context entry stays lazy so the first batch can bootstrap through
native async subprocess execution.

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
>>> async def query_batch():
...     async with AsyncControlModeEngine.for_server(server) as engine:
...         return await engine.run_batch(requests)
>>> results = asyncio.run(query_batch())
>>> [result.stdout[0] for result in results] == [
...     session.session_id,
...     window.window_id,
... ]
True
```

## Notifications and reconnects

Register desired state with
{meth}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine.add_subscription`
and
{meth}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine.set_attach_targets`
before starting the async engine when that state must be replayed after a
reconnect. Each
{meth}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine.subscribe`
consumer receives its own bounded queue, and
{attr}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine.dropped_notifications`
exposes queue overflow.

{meth}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine.subscribe`
returns an async generator, but creating that generator does not register its
queue or start the engine. If context entry stayed lazy, or you do not use the
context manager, a notification-only consumer must call
{meth}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine.start`
after a safe session exists. Registration happens when iteration first
advances. There is no public readiness handshake, so code must not assume an
event emitted before that point will be observed.

Command `%error` frames remain
{class}`~libtmux.experimental.engines.base.CommandResult` data. Timeouts and
connection failures raise a control-mode exception because no trustworthy
command result exists. Sequence anomalies are logged.
