# List panes and return typed snapshots

{class}`~libtmux.experimental.ops.ListPanes` reads panes through
{class}`~libtmux.experimental.engines.subprocess.SubprocessEngine` and returns
their snapshots in {class}`~libtmux.experimental.ops.results.ListPanesResult`.

## Example

This executable example uses an isolated live tmux server. `server`, `session`,
`window`, and `pane` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListPanes, run
>>> assert pane.pane_id is not None
>>> result = run(
...     ListPanes(),
...     SubprocessEngine.for_server(server),
... ).raise_for_status()
>>> observed = next(item for item in result.panes if item.pane_id == pane.pane_id)
>>> (
...     type(observed).__name__,
...     observed.window_id == window.window_id,
...     observed.session_id == session.session_id,
...     observed.active,
... )
('PaneSnapshot', True, True, True)
```

## Operation reference

```{tmuxop:operation} list_panes
```

## Failure and effects

The snapshots capture one read of the server and do not refresh themselves.
The operation does not change tmux state and is safe to repeat. Call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` when a failed
server read should raise.

## Related operations

- {tmuxop:op}`list_clients`
- {tmuxop:op}`list_sessions`
