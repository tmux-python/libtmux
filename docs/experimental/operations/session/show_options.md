# Show options as `name value` pairs

`ShowOptions` models `show-options` as a typed session operation and
returns `ShowOptionsResult`.

```{tmuxop:operation} show_options
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import ShowOptions, run
>>> from libtmux.experimental.ops._types import SessionId
>>> operation = ShowOptions(target=SessionId("$1"))
>>> result = run(operation, MockEngine())
>>> result.status
'complete'
```

## Failure and effects

This operation reads tmux state without changing it. It is safe to repeat.

`MockEngine` validates the command and result contract, but it does not prove
that a live target exists. A live engine reports an invalid or missing target
as a failed result; call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` to raise the
underlying error.

## Related operations

- {tmuxop:op}`set_option`
- {tmuxop:op}`has_session`
