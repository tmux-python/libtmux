# Test operations offline

The mock engines execute no tmux process. They are useful when a test should
prove operation rendering and typed result conversion without claiming that a
real server accepted the command.

## Synchronous callers

{class}`~libtmux.experimental.engines.mock.MockEngine` fabricates IDs for create
operations, returns configured lines for `capture-pane`, and reports success
for other commands.

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import CapturePane, HasSession, SplitWindow
>>> from libtmux.experimental.ops import run
>>> from libtmux.experimental.ops._types import PaneId, SessionId, WindowId
>>> engine = MockEngine(capture_lines=("first", "second"))
>>> created = run(SplitWindow(target=WindowId("@1")), engine)
>>> captured = run(CapturePane(target=PaneId("%1")), engine)
>>> existence = run(HasSession(target=SessionId("$404")), engine)
>>> created.new_pane_id, captured.lines, existence.exists
('%1', ('first', 'second'), True)
```

The `True` existence result is the boundary, not proof that `$404` exists. The
mock is stateless about server objects and succeeds for `has-session`.

## Async callers

{class}`~libtmux.experimental.engines.mock.AsyncMockEngine` applies the same
simulation behind {func}`~libtmux.experimental.ops.arun`.

```python
>>> import asyncio
>>> from libtmux.experimental.engines import AsyncMockEngine
>>> from libtmux.experimental.ops import CapturePane, SplitWindow, arun
>>> from libtmux.experimental.ops._types import PaneId, WindowId
>>> async def exercise_offline():
...     engine = AsyncMockEngine(capture_lines=("async",))
...     created = await arun(SplitWindow(target=WindowId("@1")), engine)
...     captured = await arun(CapturePane(target=PaneId("%1")), engine)
...     return created.new_pane_id, captured.lines
>>> asyncio.run(exercise_offline())
('%1', ('async',))
```

## What still needs a live engine

Use a subprocess or control-mode engine for target lookup, permissions, shell
effects, tmux version behavior, byte-level output, transport cleanup, and
failure text from the installed tmux. Mock engines cannot report a tmux version;
pass `version` explicitly when an offline test needs a specific rendering gate.
