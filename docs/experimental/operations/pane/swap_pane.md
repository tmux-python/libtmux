# Swap two panes

{class}`~libtmux.experimental.ops.SwapPane` exchanges the positions of two
panes without changing their identifiers.

## Example

This executable example uses the injected live `server`, `window`, and `pane`
context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListPanes, SplitWindow, SwapPane, run
>>> from libtmux.experimental.ops._types import PaneId, WindowId
>>> assert pane.pane_id is not None and window.window_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> created = run(
...     SplitWindow(target=WindowId(window.window_id)),
...     engine,
... ).raise_for_status()
>>> assert created.new_pane_id is not None
>>> before = {
...     item.pane_id: item.pane_index
...     for item in run(ListPanes(), engine).raise_for_status().panes
... }
>>> result = run(
...     SwapPane(
...         target=PaneId(pane.pane_id),
...         src_target=PaneId(created.new_pane_id),
...     ),
...     engine,
... ).raise_for_status()
>>> after = {
...     item.pane_id: item.pane_index
...     for item in run(ListPanes(), engine).raise_for_status().panes
... }
>>> (
...     type(result).__name__,
...     after[pane.pane_id] == before[created.new_pane_id],
...     after[created.new_pane_id] == before[pane.pane_id],
... )
('AckResult', True, True)
```

## Operation reference

```{tmuxop:operation} swap_pane
```

## Failure and effects

The panes must exist on the same server. Use `detach=True` when the current
selection should remain with the original position.

## Related operations

- {tmuxop:op}`send_keys`
- {tmuxop:op}`capture_pane`
