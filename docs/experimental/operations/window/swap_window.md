# Swap two windows

{class}`~libtmux.experimental.ops.SwapWindow` exchanges two window positions
and returns an {class}`~libtmux.experimental.ops.results.AckResult`.

## Example

This executable example uses an isolated live tmux server. `server` and
`session` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListWindows, NewWindow, SwapWindow, run
>>> from libtmux.experimental.ops._types import SessionId, WindowId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> first = run(
...     NewWindow(target=SessionId(session.session_id), name="docs-swap-first"),
...     engine,
... ).raise_for_status()
>>> second = run(
...     NewWindow(target=SessionId(session.session_id), name="docs-swap-second"),
...     engine,
... ).raise_for_status()
>>> assert first.new_id is not None and second.new_id is not None
>>> initial = run(ListWindows(), engine).raise_for_status()
>>> before = {
...     item.window_id: item.window_index
...     for item in initial.windows
...     if item.window_id in {first.new_id, second.new_id}
... }
>>> result = run(
...     SwapWindow(
...         target=WindowId(first.new_id),
...         src_target=WindowId(second.new_id),
...         detach=True,
...     ),
...     engine,
... ).raise_for_status()
>>> observed = run(ListWindows(), engine).raise_for_status()
>>> after = {
...     item.window_id: item.window_index
...     for item in observed.windows
...     if item.window_id in {first.new_id, second.new_id}
... }
>>> (
...     type(result).__name__,
...     after[first.new_id] == before[second.new_id]
...     and after[second.new_id] == before[first.new_id]
... )
('AckResult', True)
```

## Operation reference

```{tmuxop:operation} swap_window
```

## Failure and effects

This operation changes tmux state.

The before-and-after listings prove that the owned window identifiers exchange
indices. `detach=True` prevents the proof from changing the active window.

## Related operations

- {tmuxop:op}`split_window`
- {tmuxop:op}`unlink_window`
