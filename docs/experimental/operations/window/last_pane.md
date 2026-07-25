# Select the previously active pane in a window

{class}`~libtmux.experimental.ops.LastPane` selects a window's previously
active pane and returns an
{class}`~libtmux.experimental.ops.results.AckResult`.

## Example

This executable example uses an isolated live tmux server. `server` and
`session` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import (
...     LastPane,
...     ListPanes,
...     NewWindow,
...     SelectPane,
...     SplitWindow,
...     run,
... )
>>> from libtmux.experimental.ops._types import PaneId, SessionId, WindowId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> created = run(
...     NewWindow(target=SessionId(session.session_id), name="docs-last-pane"),
...     engine,
... ).raise_for_status()
>>> assert created.new_id is not None
>>> initial = run(ListPanes(), engine).raise_for_status()
>>> first_id = next(
...     item.pane_id for item in initial.panes if item.window_id == created.new_id
... )
>>> split = run(SplitWindow(target=WindowId(created.new_id)), engine).raise_for_status()
>>> assert split.new_pane_id is not None
>>> _ = run(SelectPane(target=PaneId(split.new_pane_id)), engine).raise_for_status()
>>> _ = run(SelectPane(target=PaneId(first_id)), engine).raise_for_status()
>>> result = run(
...     LastPane(target=WindowId(created.new_id)),
...     engine,
... ).raise_for_status()
>>> observed = run(ListPanes(), engine).raise_for_status()
>>> active_pane_id = next(
...     item.pane_id
...     for item in observed.panes
...     if item.window_id == created.new_id and item.active
... )
>>> type(result).__name__, active_pane_id == split.new_pane_id
('AckResult', True)
```

## Operation reference

```{tmuxop:operation} last_pane
```

## Failure and effects

This operation changes tmux state. It is safe to repeat.

The acknowledgement carries no pane state, so the example establishes a pane
history and reads the active pane back with
{class}`~libtmux.experimental.ops.ListPanes`.

## Related operations

- {tmuxop:op}`kill_window`
- {tmuxop:op}`last_window`
