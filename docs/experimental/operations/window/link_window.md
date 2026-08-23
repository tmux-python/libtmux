# Link a window into another session

{class}`~libtmux.experimental.ops.LinkWindow` links one window into another
session and returns an
{class}`~libtmux.experimental.ops.results.AckResult`.

## Example

This executable example uses an isolated live tmux server. `server` and
`session` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import (
...     LinkWindow,
...     ListWindows,
...     NewSession,
...     NewWindow,
...     run,
... )
>>> from libtmux.experimental.ops._types import SessionId, WindowId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> source = run(
...     NewWindow(target=SessionId(session.session_id), name="docs-link-source"),
...     engine,
... ).raise_for_status()
>>> destination = run(
...     NewSession(session_name="docs-link-destination"),
...     engine,
... ).raise_for_status()
>>> assert source.new_id is not None and destination.new_id is not None
>>> result = run(
...     LinkWindow(
...         target=SessionId(destination.new_id),
...         src_target=WindowId(source.new_id),
...     ),
...     engine,
... ).raise_for_status()
>>> observed = run(ListWindows(), engine).raise_for_status()
>>> locations = {
...     item.session_id
...     for item in observed.windows
...     if item.window_id == source.new_id
... }
>>> type(result).__name__, session.session_id in locations, destination.new_id in locations
('AckResult', True, True)
```

## Operation reference

```{tmuxop:operation} link_window
```

## Failure and effects

This operation changes tmux state.

The source window and destination session are local to the example.
{class}`~libtmux.experimental.ops.ListWindows` proves that the same window
identifier belongs to both sessions after the link.

## Related operations

- {tmuxop:op}`last_window`
- {tmuxop:op}`move_window`
