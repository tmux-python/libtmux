# Resize a pane

{class}`~libtmux.experimental.ops.ResizePane` changes a pane's width or height,
moves one boundary, or toggles zoom.

## Example

This executable example uses the injected live `server` and `window` context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListPanes, ResizePane, SplitWindow, run
>>> from libtmux.experimental.ops._types import PaneId, WindowId
>>> assert window.window_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> created = run(
...     SplitWindow(target=WindowId(window.window_id)),
...     engine,
... ).raise_for_status()
>>> assert created.new_pane_id is not None
>>> result = run(
...     ResizePane(target=PaneId(created.new_pane_id), height=6),
...     engine,
... ).raise_for_status()
>>> panes = run(ListPanes(), engine).raise_for_status().panes
>>> observed = next(item for item in panes if item.pane_id == created.new_pane_id)
>>> type(result).__name__, observed.height
('AckResult', 6)
```

## Operation reference

```{tmuxop:operation} resize_pane
```

## Failure and effects

tmux may constrain the requested size when neighboring panes or the terminal
make it impossible. Read the resulting geometry when the exact size matters.

## Related operations

- {tmuxop:op}`pipe_pane`
- {tmuxop:op}`respawn_pane`
