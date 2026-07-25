# Run async subprocess operations

{class}`~libtmux.experimental.engines.asyncio.AsyncSubprocessEngine` uses
{func}`asyncio.create_subprocess_exec` for command process I/O.
{func}`~libtmux.experimental.ops.arun` preserves the same operation and typed
result contract as synchronous execution.

## Dispatch independent reads concurrently

The first implicit engine-version lookup is a synchronous, memoized `tmux -V`
probe. Resolve it before entering the event loop, then pass it to
{func}`~libtmux.experimental.ops.arun` when the loop must remain nonblocking.
Each call below then owns one async command child. {func}`asyncio.gather` makes
the two independent reads concurrent;
{meth}`~libtmux.experimental.engines.asyncio.AsyncSubprocessEngine.run_batch`
would deliberately await them in order.

```python
>>> import asyncio
>>> from libtmux.experimental.engines import AsyncSubprocessEngine
>>> from libtmux.experimental.ops import DisplayMessage, arun
>>> from libtmux.experimental.ops._types import PaneId, SessionId
>>> assert session.session_id is not None
>>> assert pane is not None and pane.pane_id is not None
>>> engine = AsyncSubprocessEngine.for_server(server)
>>> version = engine.tmux_version()
>>> assert version is not None
>>> async def read_ids():
...     session_result, pane_result = await asyncio.gather(
...         arun(
...             DisplayMessage(
...                 target=SessionId(session.session_id),
...                 message="#{session_id}",
...             ),
...             engine,
...             version=version,
...         ),
...         arun(
...             DisplayMessage(
...                 target=PaneId(pane.pane_id),
...                 message="#{pane_id}",
...             ),
...             engine,
...             version=version,
...         ),
...     )
...     return (
...         session_result.raise_for_status().text,
...         pane_result.raise_for_status().text,
...     )
>>> asyncio.run(read_ids()) == (session.session_id, pane.pane_id)
True
```

## Cancellation boundary

If cancellation interrupts subprocess communication, the engine terminates and
reaps the child before re-raising {exc}`asyncio.CancelledError`. That guarantee
is about local process lifetime. It cannot undo a command tmux accepted before
the cancellation arrived.

The engine has no persistent connection and therefore no close method. Keep the
owning private server or test fixture alive until all scheduled operations have
finished.
