# Set or unset a tmux hook

{class}`~libtmux.experimental.ops.SetHook` configures a command that tmux runs
when a named session event occurs.

## Example

This executable example uses an isolated live tmux server. `server` and
`session` are injected documentation context; the standalone setup tutorial
shows the equivalent public setup and cleanup.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import SetHook, run
>>> from libtmux.experimental.ops._types import SessionId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> changed = run(
...     SetHook(
...         target=SessionId(session.session_id),
...         name="after-new-window",
...         hook_command="display-message docs-ready",
...     ),
...     engine,
... ).raise_for_status()
>>> hook = session.show_hooks()["after-new-window[0]"]
>>> type(changed).__name__, "display-message docs-ready" in hook
('AckResult', True)
```

## Operation reference

```{tmuxop:operation} set_hook
```

## Failure and effects

This operation changes tmux state.

The typed catalog does not include a show-hooks operation. The example reads
the configured hook back through {meth}`~libtmux.hooks.HooksMixin.show_hooks`.

## Related operations

- {tmuxop:op}`set_environment`
- {tmuxop:op}`set_option`
