# Rename a session

{class}`~libtmux.experimental.ops.RenameSession` changes the name of an
existing session and returns an acknowledgement.

## Example

This executable example uses an isolated live tmux server. `server` is injected
documentation context; the standalone setup tutorial shows the equivalent
public setup and cleanup.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListSessions, NewSession, RenameSession, run
>>> from libtmux.experimental.ops._types import SessionId
>>> engine = SubprocessEngine.for_server(server)
>>> created = run(
...     NewSession(session_name="docs-before"),
...     engine,
... ).raise_for_status()
>>> assert created.new_id is not None
>>> changed = run(
...     RenameSession(target=SessionId(created.new_id), name="docs-after"),
...     engine,
... ).raise_for_status()
>>> observed = run(ListSessions(), engine).raise_for_status()
>>> type(changed).__name__, next(
...     item.name for item in observed.sessions if item.session_id == created.new_id
... )
('AckResult', 'docs-after')
```

## Operation reference

```{tmuxop:operation} rename_session
```

## Failure and effects

This operation changes tmux state. It is safe to repeat.

The session identifier remains stable across the rename, so a live session
listing can read the new name back without relying on command output.

## Related operations

- {tmuxop:op}`new_window`
- {tmuxop:op}`set_environment`
