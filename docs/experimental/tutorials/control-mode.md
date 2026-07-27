# Use control mode

{class}`~libtmux.experimental.engines.control_mode.ControlModeEngine` keeps one
`tmux -C` client alive once connected and correlates tmux's framed replies with
submitted
{class}`~libtmux.experimental.engines.base.CommandRequest` values.
{meth}`~libtmux.experimental.engines.control_mode.ControlModeEngine.run_batch`
pipelines an ordered batch instead of starting one process per request.

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

## Pipeline one live batch

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
>>> [type(result).__name__ for result in results]
['CommandResult', 'CommandResult']
>>> [result.returncode for result in results]
[0, 0]
>>> [result.stdout[0] for result in results] == [
...     session.session_id,
...     window.window_id,
... ]
True
```

The values are live raw
{class}`~libtmux.experimental.engines.base.CommandResult` instances because
`run_batch` is the engine boundary. Use {func}`~libtmux.experimental.ops.run` or
a plan when the caller needs operation-specific result subtypes.

## Async variation

For
{class}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine`,
{doc}`async-control-plans` shows typed results, a forward-referenced pane, and
two control-mode dispatches. The engine reference documents its supervisor,
reconnection, and subscription boundaries without implying a public subscriber
readiness handshake.
