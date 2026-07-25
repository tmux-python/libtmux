# Rename a window

{class}`~libtmux.experimental.ops.RenameWindow` changes a window's name and
returns an {class}`~libtmux.experimental.ops.results.AckResult`.

## Example

This executable example uses an isolated live tmux server. `server` and
`session` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListWindows, NewWindow, RenameWindow, run
>>> from libtmux.experimental.ops._types import SessionId, WindowId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> created = run(
...     NewWindow(target=SessionId(session.session_id), name="docs-before"),
...     engine,
... ).raise_for_status()
>>> assert created.new_id is not None
>>> result = run(
...     RenameWindow(target=WindowId(created.new_id), name="docs-after"),
...     engine,
... ).raise_for_status()
>>> observed = run(ListWindows(), engine).raise_for_status()
>>> renamed = next(
...     item.name for item in observed.windows if item.window_id == created.new_id
... )
>>> type(result).__name__, renamed
('AckResult', 'docs-after')
```

## Operation reference

```{tmuxop:operation} rename_window
```

## Failure and effects

This operation changes tmux state. It is safe to repeat.

The operation returns no name payload. The example resolves the same window
identifier through {class}`~libtmux.experimental.ops.ListWindows` and reads its
new name independently.

## Related operations

- {tmuxop:op}`previous_window`
- {tmuxop:op}`resize_window`
