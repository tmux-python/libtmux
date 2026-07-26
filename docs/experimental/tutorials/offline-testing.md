# Test operations offline

{class}`~libtmux.experimental.engines.mock.MockEngine` and
{class}`~libtmux.experimental.engines.mock.AsyncMockEngine` execute no tmux
process. Use them to prove rendering and typed result conversion without
claiming that a real server accepted a command.

## Read canned output and fabricated IDs

{class}`~libtmux.experimental.engines.mock.MockEngine` fabricates IDs for create
operations, returns configured lines for `capture-pane`, and reports success
for other commands.

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import CapturePane, HasSession, SplitWindow
>>> from libtmux.experimental.ops import PaneId, SessionId, WindowId, run
>>> engine = MockEngine(capture_lines=("canned:first", "canned:second"))
>>> created = run(SplitWindow(target=WindowId("@1")), engine)
>>> captured = run(CapturePane(target=PaneId("%1")), engine)
>>> existence = run(HasSession(target=SessionId("$404")), engine)
>>> created.new_pane_id, captured.lines, existence.exists
('%1', ('canned:first', 'canned:second'), True)
```

`%1` is fabricated, the capture lines are canned, and `True` is simulated. None
proves that the pane, output, or `$404` session exists on a server.

## Async variation

{class}`~libtmux.experimental.engines.mock.AsyncMockEngine` applies the same
simulation behind {func}`~libtmux.experimental.ops.arun`. Use it when the code
under test is async, not to make concurrency, cancellation, or connection
lifecycle claims.

```python
>>> import asyncio
>>> from libtmux.experimental.engines import AsyncMockEngine
>>> from libtmux.experimental.ops import CapturePane, PaneId, arun
>>> async def capture_offline():
...     engine = AsyncMockEngine(capture_lines=("canned:async",))
...     return await arun(CapturePane(target=PaneId("%404")), engine)
>>> captured = asyncio.run(capture_offline()).raise_for_status()
>>> captured.lines
('canned:async',)
```

The returned line is canned. The async engine does not inspect `%404`, start
tmux, or prove that a pane emitted output.

## What still needs a live engine

Use a subprocess or control-mode engine for target lookup, permissions, shell
effects, tmux version behavior, byte-level output, transport cleanup, and
failure text from the installed tmux. Mock engines cannot report a tmux version;
pass `version` explicitly when an offline test needs a specific rendering gate.
