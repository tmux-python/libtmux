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

Within the context, pass typed operations to
{func}`~libtmux.experimental.ops.arun` as you would with any asynchronous
engine.

```python
>>> import asyncio
>>> from libtmux.experimental.engines import AsyncControlModeEngine
>>> from libtmux.experimental.ops import DisplayMessage, PaneId, arun
>>> assert pane is not None and pane.pane_id is not None
>>> async def read_pane_id():
...     async with AsyncControlModeEngine.for_server(server) as engine:
...         result = await arun(
...             DisplayMessage(target=PaneId(pane.pane_id), message="#{pane_id}"),
...             engine,
...         )
...         return result.raise_for_status().text
>>> asyncio.run(read_pane_id()) == pane.pane_id
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
boundary, while tmux command errors remain result data. The engine drains the
control process's stderr concurrently and includes its bounded recent tail in
connection and protocol failures. Cleanup joins that reader and reaps the
process before returning, including when the caller waiting on cleanup is
cancelled. A backwards command number or a solicited block with no pending
request raises a protocol error and restarts the connection rather than risking
result misattribution.

Tmux does not escape command-output lines inside these blocks. Output that
resembles a nonmatching guard remains data, but output byte-for-byte identical
to its own closing guard is indistinguishable from protocol framing. This is a
tmux control-protocol limitation; use
{class}`~libtmux.experimental.engines.asyncio.AsyncSubprocessEngine` when
arbitrary output must round-trip without that ambiguity.

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

## Pane-output bytes

{class}`~libtmux.experimental.engines.async_control_mode.ControlNotification`
keeps the encoded, human-readable control line in `raw` and its exact bytes in
`raw_bytes` for wire diagnostics. For `%output` and `%extended-output`, it also
exposes the pane ID and decoded bytes in `pane_id` and `payload`. Decode text
only at the application boundary: tmux passes pane bytes through without
validating UTF-8.

```python
>>> from libtmux.experimental.engines import ControlNotification
>>> event = ControlNotification.parse(b"%output %7 hello\\012world\\134")
>>> event.pane_id, event.payload
('%7', b'hello\nworld\\')
>>> event.raw
'%output %7 hello\\012world\\134'
```

Tmux uses a backslash followed by exactly three octal digits for an escaped
byte. Shorter octal-looking text remains literal. Consumers normally read
`payload`; `raw` remains useful when diagnosing the protocol stream.

## API

```{eval-rst}
.. autoclass:: libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine
   :members:
   :special-members: __aenter__, __aexit__

.. autoclass:: libtmux.experimental.engines.async_control_mode.ControlNotification
   :members:
```

## Related tutorial

See {doc}`../tutorials/async-control-plans` to compose forward-referenced
operations and pipeline their ordered requests over control mode.
