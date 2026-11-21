# Resize a window

{class}`~libtmux.experimental.ops.ResizeWindow` changes a window's dimensions
and returns an {class}`~libtmux.experimental.ops.results.AckResult`.

## Example

This executable example uses an isolated live tmux server. `server` and
`session` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListWindows, NewWindow, ResizeWindow, run
>>> from libtmux.experimental.ops._types import SessionId, WindowId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> created = run(
...     NewWindow(target=SessionId(session.session_id), name="docs-resize"),
...     engine,
... ).raise_for_status()
>>> assert created.new_id is not None
>>> result = run(
...     ResizeWindow(target=WindowId(created.new_id), width=90, height=30),
...     engine,
... ).raise_for_status()
>>> observed = run(ListWindows(), engine).raise_for_status()
>>> resized = next(
...     item for item in observed.windows if item.window_id == created.new_id
... )
>>> (
...     type(result).__name__,
...     resized.fields["window_width"],
...     resized.fields["window_height"],
... )
('AckResult', '90', '30')
```

## Operation reference

```{tmuxop:operation} resize_window
```

## Failure and effects

This operation changes tmux state. It changes layout.

The acknowledgement has no geometry payload, so the example reads
`window_width` and `window_height` back from a live typed window snapshot.

## Related operations

- {tmuxop:op}`rename_window`
- {tmuxop:op}`respawn_window`
