# Control-mode engine

{class}`~libtmux.experimental.engines.control_mode.ControlModeEngine` pipelines
requests over one synchronous `tmux -C` connection.

## Use it when

Use it for synchronous workloads where several commands should avoid one
process start per request.

## Avoid it when

Choose subprocess execution for isolated one-shot commands. Choose async control
mode when the event loop or notification stream is part of the application.

## Construction and cleanup

The connection opens on first use. Bind it to a live server with
{meth}`~libtmux.experimental.engines.control_mode.ControlModeEngine.for_server`,
and always call
{meth}`~libtmux.experimental.engines.control_mode.ControlModeEngine.close` or
use the context manager.

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
>>> [result.returncode for result in results]
[0, 0]
>>> results[0].stdout == (session.session_id,)
True
>>> results[1].stdout == (window.window_id,)
True
```

## Lifecycle and failure boundary

{meth}`~libtmux.experimental.engines.control_mode.ControlModeEngine.run_batch`
writes the batch before collecting correlated control-mode result blocks. The
engine drains unsolicited notifications so they are not mistaken for command
replies. Timeouts, connection death, and write failures raise
{exc}`~libtmux.experimental.engines.control_mode.ControlModeError`; tmux
`%error` blocks remain command-result data. Sequence anomalies are logged.
Context exit closes and reaps the control client.

## API

```{eval-rst}
.. autoclass:: libtmux.experimental.engines.control_mode.ControlModeEngine
   :members:
   :special-members: __enter__, __exit__
```

## Related tutorial

See {doc}`../tutorials/control-mode` for sync and async batching and lifecycle
differences.
