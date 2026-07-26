# Async mock engine

{class}`~libtmux.experimental.engines.mock.AsyncMockEngine` provides the mock
simulation through the async engine protocol.

## Use it when

Use it to exercise async application and plan code offline while preserving the
same operation rendering and typed result conversion as a live async engine.

## Avoid it when

Do not use it to test scheduling, cancellation, subprocess cleanup, control-mode
reconnection, notifications, or real tmux state.

## Construction and cleanup

Pass optional canned `capture_lines`. Create operations receive fabricated IDs.
The engine owns no task, process, or connection, so no cleanup is required.

The `%1` below is fabricated. The engine neither inspects `@404` nor creates a
pane.

```python
>>> import asyncio
>>> from libtmux.experimental.engines import AsyncMockEngine
>>> from libtmux.experimental.ops import SplitWindow, WindowId, arun
>>> operation = SplitWindow(target=WindowId("@404"))
>>> async def create_offline():
...     return await arun(operation, AsyncMockEngine())
>>> fabricated = asyncio.run(create_offline()).raise_for_status()
>>> fabricated.new_pane_id, fabricated.argv == operation.render()
('%1', True)
```

## Lifecycle and failure boundary

The async methods complete from memory, and
{meth}`~libtmux.experimental.engines.mock.AsyncMockEngine.run_batch` executes
requests in order. The simulation fabricates create IDs and canned captures but
does not model server objects or transport failure. It also cannot report a
tmux version, so operation rendering assumes the latest behavior unless the
caller supplies `version`.

## API

```{eval-rst}
.. autoclass:: libtmux.experimental.engines.mock.AsyncMockEngine
   :members:
```

## Related tutorial

See {doc}`../tutorials/offline-testing` for synchronous and asynchronous
offline test patterns.
