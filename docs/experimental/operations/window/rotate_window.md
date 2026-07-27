# Rotate the panes in a window

{class}`~libtmux.experimental.ops.RotateWindow` rotates pane positions within
a window and returns an {class}`~libtmux.experimental.ops.results.AckResult`.

## Example

This executable example uses an isolated live tmux server. `server` and
`session` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import (
...     ListPanes,
...     NewWindow,
...     RotateWindow,
...     SplitWindow,
...     run,
... )
>>> from libtmux.experimental.ops._types import SessionId, WindowId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> created = run(
...     NewWindow(target=SessionId(session.session_id), name="docs-rotate"),
...     engine,
... ).raise_for_status()
>>> assert created.new_id is not None
>>> _ = run(SplitWindow(target=WindowId(created.new_id)), engine).raise_for_status()
>>> _ = run(SplitWindow(target=WindowId(created.new_id)), engine).raise_for_status()
>>> initial = run(ListPanes(), engine).raise_for_status()
>>> before = tuple(
...     item.pane_id
...     for item in sorted(
...         (item for item in initial.panes if item.window_id == created.new_id),
...         key=lambda item: item.pane_index,
...     )
... )
>>> result = run(
...     RotateWindow(target=WindowId(created.new_id), down=True),
...     engine,
... ).raise_for_status()
>>> observed = run(ListPanes(), engine).raise_for_status()
>>> after = tuple(
...     item.pane_id
...     for item in sorted(
...         (item for item in observed.panes if item.window_id == created.new_id),
...         key=lambda item: item.pane_index,
...     )
... )
>>> type(result).__name__, len(before) == 3 and set(after) == set(before) and after != before
('AckResult', True)
```

## Operation reference

```{tmuxop:operation} rotate_window
```

## Failure and effects

This operation changes tmux state. It changes layout.

The same three pane identifiers remain after rotation, but their index order
changes. The before-and-after snapshots prove that relationship without
depending on volatile identifiers.

## Related operations

- {tmuxop:op}`respawn_window`
- {tmuxop:op}`select_layout`
