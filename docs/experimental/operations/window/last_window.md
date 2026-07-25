# Select the previously active window

{class}`~libtmux.experimental.ops.LastWindow` selects a session's previously
active window and returns an
{class}`~libtmux.experimental.ops.results.AckResult`.

## Example

This executable example uses an isolated live tmux server. `server` and
`session` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import (
...     LastWindow,
...     ListWindows,
...     NewWindow,
...     SelectWindow,
...     run,
... )
>>> from libtmux.experimental.ops._types import SessionId, WindowId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> first = run(
...     NewWindow(target=SessionId(session.session_id), name="docs-last-first"),
...     engine,
... ).raise_for_status()
>>> second = run(
...     NewWindow(target=SessionId(session.session_id), name="docs-last-second"),
...     engine,
... ).raise_for_status()
>>> assert first.new_id is not None and second.new_id is not None
>>> _ = run(SelectWindow(target=WindowId(first.new_id)), engine).raise_for_status()
>>> _ = run(SelectWindow(target=WindowId(second.new_id)), engine).raise_for_status()
>>> result = run(
...     LastWindow(target=SessionId(session.session_id)),
...     engine,
... ).raise_for_status()
>>> observed = run(ListWindows(), engine).raise_for_status()
>>> active_window_id = next(
...     item.window_id
...     for item in observed.windows
...     if item.session_id == session.session_id and item.active
... )
>>> type(result).__name__, active_window_id == first.new_id
('AckResult', True)
```

## Operation reference

```{tmuxop:operation} last_window
```

## Failure and effects

This operation changes tmux state. It is safe to repeat.

The example owns both history entries, then resolves the active window through
{class}`~libtmux.experimental.ops.ListWindows`.

## Related operations

- {tmuxop:op}`last_pane`
- {tmuxop:op}`link_window`
