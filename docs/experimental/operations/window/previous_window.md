# Select the previous window in a session

{class}`~libtmux.experimental.ops.PreviousWindow` selects the preceding window
in a session and returns an
{class}`~libtmux.experimental.ops.results.AckResult`.

## Example

This executable example uses an isolated live tmux server. `server` and
`session` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import (
...     ListWindows,
...     NewWindow,
...     PreviousWindow,
...     SelectWindow,
...     run,
... )
>>> from libtmux.experimental.ops._types import SessionId, WindowId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> first = run(
...     NewWindow(target=SessionId(session.session_id), name="docs-previous-first"),
...     engine,
... ).raise_for_status()
>>> second = run(
...     NewWindow(target=SessionId(session.session_id), name="docs-previous-second"),
...     engine,
... ).raise_for_status()
>>> assert first.new_id is not None and second.new_id is not None
>>> _ = run(SelectWindow(target=WindowId(second.new_id)), engine).raise_for_status()
>>> result = run(
...     PreviousWindow(target=SessionId(session.session_id)),
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

```{tmuxop:operation} previous_window
```

## Failure and effects

This operation changes tmux state.

The example creates adjacent windows, selects the second, and resolves the
active window after moving backward. The final relationship is stronger
evidence than the acknowledgement alone.

## Related operations

- {tmuxop:op}`next_window`
- {tmuxop:op}`rename_window`
