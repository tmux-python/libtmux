# List the server's sessions and return typed snapshots

{class}`~libtmux.experimental.ops.ListSessions` reads sessions through
{class}`~libtmux.experimental.engines.subprocess.SubprocessEngine` and returns
their snapshots in
{class}`~libtmux.experimental.ops.results.ListSessionsResult`.

## Example

This executable example uses an isolated live tmux server. `server`, `session`,
`window`, and `pane` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListSessions, run
>>> assert session.session_id is not None
>>> result = run(
...     ListSessions(),
...     SubprocessEngine.for_server(server),
... ).raise_for_status()
>>> observed = next(
...     item for item in result.sessions if item.session_id == session.session_id
... )
>>> (
...     type(observed).__name__,
...     observed.name == session.session_name,
...     observed.session_id == session.session_id,
... )
('SessionSnapshot', True, True)
```

## Operation reference

```{tmuxop:operation} list_sessions
```

## Failure and effects

The snapshots capture one read of the server and do not refresh themselves.
The operation does not change tmux state and is safe to repeat. Call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` when a failed
server read should raise.

## Related operations

- {tmuxop:op}`list_panes`
- {tmuxop:op}`list_windows`
