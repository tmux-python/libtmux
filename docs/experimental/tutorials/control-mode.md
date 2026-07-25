# Use control mode

Control-mode engines keep one `tmux -C` client alive and correlate tmux's
framed replies with submitted
{class}`~libtmux.experimental.engines.base.CommandRequest` values.
{meth}`~libtmux.experimental.engines.control_mode.ControlModeEngine.run_batch`
and
{meth}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine.run_batch`
pipeline commands instead of starting one process per request.

## Synchronous batch

Use {class}`~libtmux.experimental.engines.control_mode.ControlModeEngine` as a
context manager so the persistent control client is closed on every exit path.

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

The async context starts and closes
{class}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine`.
Its supervisor owns the reader and reconnect loop.

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
queue. Registration happens when iteration first advances. There is no public
readiness handshake, so code must not assume an event emitted before that point
will be observed.

Command `%error` frames remain
{class}`~libtmux.experimental.engines.base.CommandResult` data. Timeouts and
connection failures raise a control-mode exception because no trustworthy
command result exists. Sequence anomalies are logged.
