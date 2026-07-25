# Set the contents of a paste buffer

`SetBuffer` models `set-buffer` as a typed server operation and
returns `AckResult`.

```{tmuxop:operation} set_buffer
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import SetBuffer, run
>>> operation = SetBuffer(data="build output", buffer_name="build")
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

- {tmuxop:op}`save_buffer`
- {tmuxop:op}`show_buffer`
