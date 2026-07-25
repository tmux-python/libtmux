# Restart the command in a (usually dead) window

{class}`~libtmux.experimental.ops.RespawnWindow` replaces the process in a
window and returns an {class}`~libtmux.experimental.ops.results.AckResult`.

## Example

This executable example uses an isolated live tmux server. `server` and
`session` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListPanes, NewWindow, RespawnWindow, run
>>> from libtmux.experimental.ops._types import SessionId, WindowId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> created = run(
...     NewWindow(
...         target=SessionId(session.session_id),
...         name="docs-respawn",
...         window_shell="sleep 300",
...     ),
...     engine,
... ).raise_for_status()
>>> assert created.new_id is not None
>>> initial = run(ListPanes(), engine).raise_for_status()
>>> before_pid = next(
...     item.pid for item in initial.panes if item.window_id == created.new_id
... )
>>> result = run(
...     RespawnWindow(
...         target=WindowId(created.new_id),
...         kill=True,
...         shell="sleep 300",
...     ),
...     engine,
... ).raise_for_status()
>>> observed = run(ListPanes(), engine).raise_for_status()
>>> after_pid = next(
...     item.pid for item in observed.panes if item.window_id == created.new_id
... )
>>> (
...     type(result).__name__,
...     before_pid is not None and after_pid is not None and after_pid != before_pid,
... )
('AckResult', True)
```

## Operation reference

```{tmuxop:operation} respawn_window
```

## Failure and effects

This operation changes tmux state.

The example creates the process it replaces and compares the pane PID before
and after the acknowledgement. `kill=True` is required while the original
process is still running.

## Related operations

- {tmuxop:op}`resize_window`
- {tmuxop:op}`rotate_window`
