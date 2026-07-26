# Control-mode engine

{class}`~libtmux.experimental.engines.control_mode.ControlModeEngine` pipelines
requests over one synchronous `tmux -C` connection once it can attach to a
session safely. Before then, it dispatches through subprocesses.

## Use it when

Use it for synchronous workloads where several commands should avoid one
process start per request.

## Avoid it when

Choose subprocess execution for isolated one-shot commands. Choose async control
mode when the event loop or notification stream is part of the application.

## Construction and cleanup

Bind the engine to a live server with
{meth}`~libtmux.experimental.engines.control_mode.ControlModeEngine.for_server`,
and always call
{meth}`~libtmux.experimental.engines.control_mode.ControlModeEngine.close` or
use the context manager. The context is lazy: the first batch looks for an
existing session whose effective `destroy-unattached` value is `off`. The
engine attaches to that exact session ID with `attach-session -E`, so tmux does
not choose a different session and does not apply `update-environment`.

If no safe session exists, the batch uses
{class}`~libtmux.experimental.engines.subprocess.SubprocessEngine` instead.
This lets `new-session` bootstrap an empty server without creating a private
control session. A later batch can open the persistent connection.

Within the context, pass typed operations to
{func}`~libtmux.experimental.ops.run` as you would with any synchronous engine.

```python
>>> from libtmux.experimental.engines import ControlModeEngine
>>> from libtmux.experimental.ops import DisplayMessage, PaneId, run
>>> assert pane is not None and pane.pane_id is not None
>>> with ControlModeEngine.for_server(server) as engine:
...     result = run(
...         DisplayMessage(target=PaneId(pane.pane_id), message="#{pane_id}"),
...         engine,
...     ).raise_for_status()
>>> result.text == pane.pane_id
True
```

## Lifecycle and failure boundary

{meth}`~libtmux.experimental.engines.control_mode.ControlModeEngine.run_batch`
writes the batch before collecting correlated control-mode result blocks. The
engine drains unsolicited notifications so they are not mistaken for command
replies. Timeouts, connection death, and write failures raise
{exc}`~libtmux.experimental.engines.control_mode.ControlModeError`; tmux
`%error` blocks remain command-result data. Sequence anomalies are logged.

The persistent process has normal tmux client semantics: `list-clients` shows
it, `session_attached` includes it, and client attach and detach hooks can
observe it. The engine never changes `destroy-unattached` and does not issue a
session-deletion command during cleanup. If that option changes while the
client is attached, closing the engine detaches normally and tmux applies the
new policy.

## API

```{eval-rst}
.. autoclass:: libtmux.experimental.engines.control_mode.ControlModeEngine
   :members:
   :special-members: __enter__, __exit__
```

## Related tutorial

See {doc}`../tutorials/control-mode` for ordered pipelining over one synchronous
control client.
