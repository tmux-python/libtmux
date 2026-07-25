# Kill a window

{class}`~libtmux.experimental.ops.KillWindow` destroys one window and returns
an {class}`~libtmux.experimental.ops.results.AckResult`.

## Example

This executable example uses an isolated live tmux server. `server` and
`session` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import KillWindow, ListWindows, NewWindow, run
>>> from libtmux.experimental.ops._types import SessionId, WindowId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> created = run(
...     NewWindow(target=SessionId(session.session_id), name="docs-kill-window"),
...     engine,
... ).raise_for_status()
>>> assert created.new_id is not None
>>> before = run(ListWindows(), engine).raise_for_status()
>>> result = run(
...     KillWindow(target=WindowId(created.new_id)),
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

```{tmuxop:operation} kill_window
```

## Failure and effects

This operation is destructive and cannot be undone.

The example creates the window it destroys and proves both its presence and
absence with independent live listings. A missing target produces a failed
result; {meth}`~libtmux.experimental.ops.results.Result.raise_for_status`
raises the underlying error.

## Related operations

- {tmuxop:op}`break_pane`
- {tmuxop:op}`last_pane`
