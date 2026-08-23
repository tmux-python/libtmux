# Read session options

{class}`~libtmux.experimental.ops.ShowOptions` parses tmux option output into a
typed name-to-value mapping.

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
>>> _ = run(
...     SetOption(target=target, option="@docs_visible", value="yes"),
...     engine,
... ).raise_for_status()
>>> result = run(ShowOptions(target=target), engine).raise_for_status()
>>> type(result).__name__, result.options["@docs_visible"]
('ShowOptionsResult', 'yes')
```

## Operation reference

```{tmuxop:operation} show_options
```

## Failure and effects

This operation reads tmux state without changing it. It is safe to repeat.

Without `include_inherited=True`, the mapping contains only options set at the
selected scope.

## Related operations

- {tmuxop:op}`set_option`
- {tmuxop:op}`has_session`
