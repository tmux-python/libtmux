# Set a window option

{class}`~libtmux.experimental.ops.SetWindowOption` changes a window-scoped
option and returns an {class}`~libtmux.experimental.ops.results.AckResult`.

## Example

This executable example uses an isolated live tmux server. `server` and
`session` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import (
...     NewWindow,
...     SetWindowOption,
...     ShowOptions,
...     run,
... )
>>> from libtmux.experimental.ops._types import SessionId, WindowId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> created = run(
...     NewWindow(target=SessionId(session.session_id), name="docs-window-option"),
...     engine,
... ).raise_for_status()
>>> assert created.new_id is not None
>>> target = WindowId(created.new_id)
>>> result = run(
...     SetWindowOption(
...         target=target,
...         option="@libtmux_docs_window",
...         value="enabled",
...     ),
...     engine,
... ).raise_for_status()
>>> observed = run(
...     ShowOptions(target=target, window=True),
...     engine,
... ).raise_for_status()
>>> type(result).__name__, observed.options["@libtmux_docs_window"]
('AckResult', 'enabled')
```

## Operation reference

```{tmuxop:operation} set_window_option
```

## Failure and effects

This operation changes tmux state.

The custom option is scoped to a window created by the example and read back
with {class}`~libtmux.experimental.ops.ShowOptions`. Use `unset=True` to remove
an option instead of assigning a value.

## Related operations

- {tmuxop:op}`select_window`
- {tmuxop:op}`split_window`
