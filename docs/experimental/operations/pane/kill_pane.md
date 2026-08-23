# Kill a pane

{class}`~libtmux.experimental.ops.KillPane` stops the process in one pane and
removes the pane from its window.

## Example

This executable example uses the injected live `server` and `window` context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import KillPane, ListPanes, SplitWindow, run
>>> from libtmux.experimental.ops._types import PaneId, WindowId
>>> assert window.window_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> created = run(
...     SplitWindow(target=WindowId(window.window_id)),
...     engine,
... ).raise_for_status()
>>> assert created.new_pane_id is not None
>>> before = run(ListPanes(), engine).raise_for_status()
>>> result = run(
...     KillPane(target=PaneId(created.new_pane_id)),
...     engine,
... ).raise_for_status()
>>> after = run(ListPanes(), engine).raise_for_status()
>>> (
...     type(result).__name__,
...     created.new_pane_id in {item.pane_id for item in before.panes},
...     created.new_pane_id not in {item.pane_id for item in after.panes},
... )
('AckResult', True, True)
```

## Operation reference

```{tmuxop:operation} kill_pane
```

## Failure and effects

This operation is destructive and cannot be undone. The example creates a
disposable second pane instead of targeting the fixture's primary pane.

## Related operations

- {tmuxop:op}`join_pane`
- {tmuxop:op}`move_pane`
