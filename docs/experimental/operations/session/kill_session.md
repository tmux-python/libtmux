# Kill a session

{class}`~libtmux.experimental.ops.KillSession` removes one session and all of
its windows and panes.

## Example

This executable example uses an isolated live tmux server. `server` is injected
documentation context; the standalone setup tutorial shows the equivalent
public setup and cleanup.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import HasSession, KillSession, NewSession, run
>>> from libtmux.experimental.ops._types import SessionId
>>> engine = SubprocessEngine.for_server(server)
>>> created = run(
...     NewSession(session_name="docs-disposable"),
...     engine,
... ).raise_for_status()
>>> assert created.new_id is not None
>>> target = SessionId(created.new_id)
>>> run(HasSession(target=target), engine).exists
True
>>> result = run(KillSession(target=target), engine).raise_for_status()
>>> type(result).__name__, run(HasSession(target=target), engine).exists
('AckResult', False)
```

## Operation reference

```{tmuxop:operation} kill_session
```

## Failure and effects

This operation is destructive and cannot be undone.

The example creates and removes a disposable session so the documentation
fixture remains available for cleanup and later assertions.

## Related operations

- {tmuxop:op}`has_session`
- {tmuxop:op}`new_window`
