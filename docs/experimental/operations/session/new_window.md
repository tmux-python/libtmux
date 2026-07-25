# Create a window in a session

{class}`~libtmux.experimental.ops.NewWindow` creates a window and captures its
tmux identifier in a typed creation result.

## Example

This executable example uses an isolated live tmux server. `server` and
`session` are injected documentation context; the standalone setup tutorial
shows the equivalent public setup and cleanup.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListWindows, NewWindow, run
>>> from libtmux.experimental.ops._types import SessionId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> created = run(
...     NewWindow(target=SessionId(session.session_id), name="docs-build"),
...     engine,
... ).raise_for_status()
>>> assert created.new_id is not None
>>> observed = run(ListWindows(), engine).raise_for_status()
>>> next(item.name for item in observed.windows if item.window_id == created.new_id)
'docs-build'
```

## Operation reference

```{tmuxop:operation} new_window
```

## Failure and effects

This operation changes tmux state. It creates a window.

The captured identifier is resolved through a second live operation; a
non-`None` identifier alone would not prove that tmux created the window.

## Related operations

- {tmuxop:op}`kill_session`
- {tmuxop:op}`rename_session`
