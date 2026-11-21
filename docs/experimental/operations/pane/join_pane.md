# Join a pane into another window

{class}`~libtmux.experimental.ops.JoinPane` moves a source pane into a
destination window and splits the destination around it.

## Example

This executable example uses the injected live `server`, `session`, and
`window` context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import JoinPane, ListPanes, NewWindow, run
>>> from libtmux.experimental.ops._types import PaneId, SessionId, WindowId
>>> assert session.session_id is not None and window.window_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> created = run(
...     NewWindow(
...         target=SessionId(session.session_id),
...         name="docs-join-source",
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
...     JoinPane(
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

```{tmuxop:operation} join_pane
```

## Failure and effects

Moving the only pane out of its source window removes that empty window. Both
targets must belong to the same tmux server.

## Related operations

- {tmuxop:op}`display_message`
- {tmuxop:op}`kill_pane`
