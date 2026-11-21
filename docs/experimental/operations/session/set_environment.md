# Set or unset a session environment variable

{class}`~libtmux.experimental.ops.SetEnvironment` changes the environment
inherited by new processes in a session.

## Example

This executable example uses an isolated live tmux server. `server` and
`session` are injected documentation context; the standalone setup tutorial
shows the equivalent public setup and cleanup.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import SetEnvironment, run
>>> from libtmux.experimental.ops._types import SessionId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> changed = run(
...     SetEnvironment(
...         target=SessionId(session.session_id),
...         name="LIBTMUX_DOC_MODE",
...         value="live",
...     ),
...     engine,
... ).raise_for_status()
>>> type(changed).__name__, session.getenv("LIBTMUX_DOC_MODE")
('AckResult', 'live')
```

## Operation reference

```{tmuxop:operation} set_environment
```

## Failure and effects

This operation changes tmux state.

The typed operation has no matching typed read operation, so the example uses
{meth}`~libtmux.common.EnvironmentMixin.getenv` for the independent readback.

## Related operations

- {tmuxop:op}`rename_session`
- {tmuxop:op}`set_hook`
