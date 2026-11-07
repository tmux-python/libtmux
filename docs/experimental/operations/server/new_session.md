# Create a detached session and capture its ID

{class}`~libtmux.experimental.ops.NewSession` creates a detached session through
{class}`~libtmux.experimental.engines.subprocess.SubprocessEngine` and captures
its ID in {class}`~libtmux.experimental.ops.results.CreateResult`.

## Example

This executable example uses an isolated live tmux server. `server`, `session`,
`window`, and `pane` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import KillSession, ListSessions, NewSession, run
>>> from libtmux.experimental.ops._types import SessionId
>>> engine = SubprocessEngine.for_server(server)
>>> created = run(
...     NewSession(session_name="docs-created"),
...     engine,
... ).raise_for_status()
>>> assert created.new_id is not None
>>> observed = run(ListSessions(), engine).raise_for_status()
>>> snapshot = next(
...     item for item in observed.sessions if item.session_id == created.new_id
... )
>>> proof = type(created).__name__, snapshot.name, snapshot.session_id == created.new_id
>>> _ = run(
...     KillSession(target=SessionId(created.new_id)),
...     engine,
... ).raise_for_status()
>>> proof
('CreateResult', 'docs-created', True)
```

## Operation reference

```{tmuxop:operation} new_session
```

## Failure and effects

The captured ID resolves the session without relying on its generated numeric
value. A duplicate session name returns a failed result. Call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` to raise that
error. The example removes the session it creates.

## Related operations

- {tmuxop:op}`load_buffer`
- {tmuxop:op}`run_shell`
