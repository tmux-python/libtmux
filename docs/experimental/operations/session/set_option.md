# Set a tmux option (`set-option`); the write counterpart to show-options

`SetOption` models `set-option` as a typed session operation and
returns `AckResult`.

```{tmuxop:operation} set_option
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import SetOption, run
>>> from libtmux.experimental.ops._types import SessionId
>>> operation = SetOption(target=SessionId("$1"), option="status", value="on")
>>> result = run(operation, MockEngine())
>>> result.status
'complete'
```

## Failure and effects

This operation changes tmux state.

`MockEngine` validates the command and result contract, but it does not prove
that a live target exists. A live engine reports an invalid or missing target
as a failed result; call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` to raise the
underlying error.

## Related operations

- {tmuxop:op}`set_hook`
- {tmuxop:op}`show_options`
