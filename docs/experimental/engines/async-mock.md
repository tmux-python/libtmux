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

Pass optional canned `capture_lines`. It owns no task, process, or connection,
so no cleanup is required.

```python
>>> import asyncio
>>> from libtmux.experimental.engines import AsyncMockEngine
>>> from libtmux.experimental.ops import CapturePane, arun
>>> from libtmux.experimental.ops._types import PaneId
>>> async def capture_offline():
...     engine = AsyncMockEngine(capture_lines=("offline",))
...     return await arun(CapturePane(target=PaneId("%1")), engine)
>>> asyncio.run(capture_offline()).lines
('offline',)
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

See {doc}`../tutorials/offline-testing` for parallel sync and async test
patterns.
