# Check whether a session exists

{class}`~libtmux.experimental.ops.HasSession` asks the server whether a
session target exists and returns a typed boolean result.

## Example

This executable example uses an isolated live tmux server. `server` and
`session` are injected documentation context; the standalone setup tutorial
shows the equivalent public setup and cleanup.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import HasSession, run
>>> from libtmux.experimental.ops._types import NameRef, SessionId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> present = run(HasSession(target=SessionId(session.session_id)), engine)
>>> missing = run(HasSession(target=NameRef("docs-missing-session")), engine)
>>> present.status, present.exists, missing.status, missing.exists
('complete', True, 'complete', False)
```

## Operation reference

```{tmuxop:operation} has_session
```

## Failure and effects

This operation reads tmux state without changing it. It is safe to repeat.

A missing session is a successful existence query with `exists=False`; it is
not a failed command result.

## Related operations

- {tmuxop:op}`show_options`
- {tmuxop:op}`kill_session`
