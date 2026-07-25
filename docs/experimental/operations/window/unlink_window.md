# Unlink a window from a session

{class}`~libtmux.experimental.ops.UnlinkWindow` removes a window link and
returns an {class}`~libtmux.experimental.ops.results.AckResult`.

## Example

This executable example uses an isolated live tmux server. `server` and
`session` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListWindows, NewWindow, UnlinkWindow, run
>>> from libtmux.experimental.ops._types import SessionId, WindowId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> created = run(
...     NewWindow(target=SessionId(session.session_id), name="docs-unlink"),
...     engine,
... ).raise_for_status()
>>> assert created.new_id is not None
>>> before = run(ListWindows(), engine).raise_for_status()
>>> result = run(
...     UnlinkWindow(target=WindowId(created.new_id), kill=True),
...     engine,
... ).raise_for_status()
>>> after = run(ListWindows(), engine).raise_for_status()
>>> (
...     type(result).__name__,
...     created.new_id in {item.window_id for item in before.windows},
...     created.new_id not in {item.window_id for item in after.windows},
... )
('AckResult', True, True)
```

## Operation reference

```{tmuxop:operation} unlink_window
```

## Failure and effects

This operation changes tmux state.

The example owns the link it removes and uses `kill=True`, so no other session
can retain the disposable window. Independent listings prove presence before
the operation and absence afterward.

## Related operations

- {tmuxop:op}`swap_window`
- {tmuxop:op}`break_pane`
