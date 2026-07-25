# Set or unset a tmux hook

`SetHook` models `set-hook` as a typed session operation and
returns `AckResult`.

```{tmuxop:operation} set_hook
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import SetHook, run
>>> from libtmux.experimental.ops._types import SessionId
>>> operation = SetHook(target=SessionId("$1"), name="after-new-window", hook_command="display-message ready")
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

- {tmuxop:op}`set_environment`
- {tmuxop:op}`set_option`
