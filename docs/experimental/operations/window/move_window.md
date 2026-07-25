# Move a window to a new index/session

{class}`~libtmux.experimental.ops.MoveWindow` transfers a window to another
session or index and returns an
{class}`~libtmux.experimental.ops.results.AckResult`.

## Example

This executable example uses an isolated live tmux server. `server` and
`session` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import (
...     ListWindows,
...     MoveWindow,
...     NewSession,
...     NewWindow,
...     run,
... )
>>> from libtmux.experimental.ops._types import SessionId, WindowId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> source = run(
...     NewWindow(target=SessionId(session.session_id), name="docs-move-source"),
...     engine,
... ).raise_for_status()
>>> destination = run(
...     NewSession(session_name="docs-move-destination"),
...     engine,
... ).raise_for_status()
>>> assert source.new_id is not None and destination.new_id is not None
>>> result = run(
...     MoveWindow(
...         target=SessionId(destination.new_id),
...         src_target=WindowId(source.new_id),
...     ),
...     engine,
... ).raise_for_status()
>>> observed = run(ListWindows(), engine).raise_for_status()
>>> destination_session_id = next(
...     item.session_id
...     for item in observed.windows
...     if item.window_id == source.new_id
... )
>>> type(result).__name__, destination_session_id == destination.new_id
('AckResult', True)
```

## Operation reference

```{tmuxop:operation} move_window
```

## Failure and effects

This operation changes tmux state.

The source window and destination session are local to the example. The final
listing resolves the moved identifier under its new session rather than
trusting the acknowledgement alone.

## Related operations

- {tmuxop:op}`link_window`
- {tmuxop:op}`new_pane`
