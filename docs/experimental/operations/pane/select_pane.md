# Select a pane

{class}`~libtmux.experimental.ops.SelectPane` makes one pane active or moves the
selection in a direction.

## Example

This executable example uses the injected live `server`, `window`, and `pane`
context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListPanes, SelectPane, SplitWindow, run
>>> from libtmux.experimental.ops._types import PaneId, WindowId
>>> assert pane.pane_id is not None and window.window_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> created = run(
...     SplitWindow(target=WindowId(window.window_id)),
...     engine,
... ).raise_for_status()
>>> assert created.new_pane_id is not None
>>> result = run(
...     SelectPane(target=PaneId(pane.pane_id)),
...     engine,
... ).raise_for_status()
>>> panes = run(ListPanes(), engine).raise_for_status().panes
>>> selected = next(item for item in panes if item.pane_id == pane.pane_id)
>>> other = next(item for item in panes if item.pane_id == created.new_pane_id)
>>> type(result).__name__, selected.active, other.active
('AckResult', True, False)
```

## Operation reference

```{tmuxop:operation} select_pane
```

## Failure and effects

Selection changes the active pane for clients viewing the window. Repeating an
explicit selection is safe.

## Related operations

- {tmuxop:op}`respawn_pane`
- {tmuxop:op}`send_keys`
