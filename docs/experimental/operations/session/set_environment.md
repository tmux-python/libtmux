# Set or unset a session environment variable

`SetEnvironment` models `set-environment` as a typed session operation and
returns `AckResult`.

```{tmuxop:operation} set_environment
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import SetEnvironment, run
>>> from libtmux.experimental.ops._types import SessionId
>>> operation = SetEnvironment(target=SessionId("$1"), name="MODE", value="build")
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

- {tmuxop:op}`rename_session`
- {tmuxop:op}`set_hook`
