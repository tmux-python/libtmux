# Apply a layout to a window

{class}`~libtmux.experimental.ops.SelectLayout` applies a named or serialized
layout and returns an {class}`~libtmux.experimental.ops.results.AckResult`.

## Example

This executable example uses an isolated live tmux server. `server` and
`session` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import (
...     ListPanes,
...     NewWindow,
...     SelectLayout,
...     SplitWindow,
...     run,
... )
>>> from libtmux.experimental.ops._types import SessionId, WindowId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> created = run(
...     NewWindow(target=SessionId(session.session_id), name="docs-layout"),
...     engine,
... ).raise_for_status()
>>> assert created.new_id is not None
>>> _ = run(SplitWindow(target=WindowId(created.new_id)), engine).raise_for_status()
>>> result = run(
...     SelectLayout(
...         target=WindowId(created.new_id),
...         layout="even-horizontal",
...     ),
...     engine,
... ).raise_for_status()
>>> observed = run(ListPanes(), engine).raise_for_status()
>>> widths = [
...     item.width for item in observed.panes if item.window_id == created.new_id
... ]
>>> (
...     type(result).__name__,
...     len(widths) == 2 and None not in widths and max(widths) - min(widths) <= 1,
... )
('AckResult', True)
```

## Operation reference

```{tmuxop:operation} select_layout
```

## Failure and effects

This operation changes tmux state. It changes layout, is safe to repeat.

`even-horizontal` divides the owned window into equal-width panes. The live
pane widths provide a stable layout postcondition; the serialized
`window_layout` string itself is intentionally opaque.

## Related operations

- {tmuxop:op}`rotate_window`
- {tmuxop:op}`select_window`
