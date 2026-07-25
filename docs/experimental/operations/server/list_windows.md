# List windows and return typed snapshots

{class}`~libtmux.experimental.ops.ListWindows` reads windows through
{class}`~libtmux.experimental.engines.subprocess.SubprocessEngine` and returns
their snapshots in
{class}`~libtmux.experimental.ops.results.ListWindowsResult`.

## Example

This executable example uses an isolated live tmux server. `server`, `session`,
`window`, and `pane` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListWindows, run
>>> assert window.window_id is not None
>>> result = run(
...     ListWindows(),
...     SubprocessEngine.for_server(server),
... ).raise_for_status()
>>> observed = next(
...     item for item in result.windows if item.window_id == window.window_id
... )
>>> (
...     type(observed).__name__,
...     observed.name == window.window_name,
...     observed.session_id == session.session_id,
... )
('WindowSnapshot', True, True)
```

## Operation reference

```{tmuxop:operation} list_windows
```

## Failure and effects

The snapshots capture one read of the server and do not refresh themselves.
The operation does not change tmux state and is safe to repeat. Call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` when a failed
server read should raise.

## Related operations

- {tmuxop:op}`list_sessions`
- {tmuxop:op}`load_buffer`
