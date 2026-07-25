# Make a window active

{class}`~libtmux.experimental.ops.SelectWindow` makes a window active and
returns an {class}`~libtmux.experimental.ops.results.AckResult`.

## Example

This executable example uses an isolated live tmux server. `server` and
`session` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListWindows, NewWindow, SelectWindow, run
>>> from libtmux.experimental.ops._types import SessionId, WindowId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> created = run(
...     NewWindow(target=SessionId(session.session_id), name="docs-select"),
...     engine,
... ).raise_for_status()
>>> assert created.new_id is not None
>>> result = run(
...     SelectWindow(target=WindowId(created.new_id)),
...     engine,
... ).raise_for_status()
>>> observed = run(ListWindows(), engine).raise_for_status()
>>> selected = next(
...     item.active for item in observed.windows if item.window_id == created.new_id
... )
>>> type(result).__name__, selected
('AckResult', True)
```

## Operation reference

```{tmuxop:operation} select_window
```

## Failure and effects

This operation changes tmux state. It is safe to repeat.

The example reads the selected window back through
{class}`~libtmux.experimental.ops.ListWindows`; the acknowledgement itself
contains no active-window state.

## Related operations

- {tmuxop:op}`select_layout`
- {tmuxop:op}`set_window_option`
