# Set a session option

{class}`~libtmux.experimental.ops.SetOption` changes one tmux option at the
session, server, window, or pane scope.

## Example

This executable example uses an isolated live tmux server. `server` and
`session` are injected documentation context; the standalone setup tutorial
shows the equivalent public setup and cleanup.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import SetOption, ShowOptions, run
>>> from libtmux.experimental.ops._types import SessionId
>>> assert session.session_id is not None
>>> target = SessionId(session.session_id)
>>> engine = SubprocessEngine.for_server(server)
>>> changed = run(
...     SetOption(target=target, option="@docs_mode", value="live"),
...     engine,
... ).raise_for_status()
>>> observed = run(ShowOptions(target=target), engine).raise_for_status()
>>> type(changed).__name__, observed.options["@docs_mode"]
('AckResult', 'live')
```

## Operation reference

```{tmuxop:operation} set_option
```

## Failure and effects

This operation changes tmux state.

An acknowledgement confirms dispatch. The separate {tmuxop:op}`show_options`
operation proves the stored value.

## Related operations

- {tmuxop:op}`set_hook`
- {tmuxop:op}`show_options`
