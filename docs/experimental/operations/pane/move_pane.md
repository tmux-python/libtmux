# Move a pane into another window

{class}`~libtmux.experimental.ops.MovePane` relocates a source pane into a
destination window while preserving the pane identifier.

## Example

This executable example uses the injected live `server`, `session`, and
`window` context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListPanes, MovePane, NewWindow, run
>>> from libtmux.experimental.ops._types import PaneId, SessionId, WindowId
>>> assert session.session_id is not None and window.window_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> created = run(
...     NewWindow(
...         target=SessionId(session.session_id),
...         name="docs-move-source",
...         capture_pane=True,
...     ),
...     engine,
... ).raise_for_status()
>>> assert created.new_id is not None and created.first_pane_id is not None
>>> before = run(ListPanes(), engine).raise_for_status()
>>> source = next(
...     item for item in before.panes if item.pane_id == created.first_pane_id
... )
>>> result = run(
...     MovePane(
...         target=WindowId(window.window_id),
...         src_target=PaneId(source.pane_id),
...     ),
...     engine,
... ).raise_for_status()
>>> after = run(ListPanes(), engine).raise_for_status()
>>> moved = next(item for item in after.panes if item.pane_id == source.pane_id)
>>> type(result).__name__, source.window_id == created.new_id, moved.window_id == window.window_id
('AckResult', True, True)
```

## Operation reference

```{tmuxop:operation} move_pane
```

## Failure and effects

The operation changes pane ownership and layout. Moving the only pane out of a
window removes the empty source window.

## Related operations

- {tmuxop:op}`kill_pane`
- {tmuxop:op}`paste_buffer`
