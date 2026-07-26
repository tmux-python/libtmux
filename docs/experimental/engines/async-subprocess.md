# Async subprocess engine

{class}`~libtmux.experimental.engines.asyncio.AsyncSubprocessEngine` runs each
request with native asyncio subprocess I/O.

## Use it when

Use this engine for typed tmux operations inside an async application when each
request may own a short-lived child process.

## Avoid it when

Choose async control mode when batches should be pipelined over one connection
or the application consumes control-mode notifications.

## Construction and cleanup

Construct it with explicit connection arguments, or bind it with
{meth}`~libtmux.experimental.engines.asyncio.AsyncSubprocessEngine.for_server`.
It has no persistent resource or close method; each
{meth}`~libtmux.experimental.engines.asyncio.AsyncSubprocessEngine.run` call
reaps its child.

```python
>>> import asyncio
>>> from libtmux.experimental.engines import AsyncSubprocessEngine
>>> from libtmux.experimental.ops import DisplayMessage, PaneId, arun
>>> assert pane is not None and pane.pane_id is not None
>>> async def read_pane_id():
...     engine = AsyncSubprocessEngine.for_server(server)
...     result = await arun(
...         DisplayMessage(target=PaneId(pane.pane_id), message="#{pane_id}"),
...         engine,
...     )
...     return result.raise_for_status().text
>>> asyncio.run(read_pane_id()) == pane.pane_id
True
```

## Lifecycle and failure boundary

{meth}`~libtmux.experimental.engines.asyncio.AsyncSubprocessEngine.run_batch`
awaits requests sequentially to preserve command order. Separate
{meth}`~libtmux.experimental.engines.asyncio.AsyncSubprocessEngine.run` or
{func}`~libtmux.experimental.ops.arun` calls may be scheduled concurrently by
the caller. If a task is cancelled while the child is running, the engine
terminates and reaps that child before propagating cancellation. Cancellation
cannot roll back a tmux mutation the server already accepted.

## API

```{eval-rst}
.. autoclass:: libtmux.experimental.engines.asyncio.AsyncSubprocessEngine
   :members:
```

## Related tutorial

See {doc}`../tutorials/async-subprocess` for concurrent operation dispatch and
cancellation boundaries.
