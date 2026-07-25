# Load a paste buffer from a file

`LoadBuffer` models `load-buffer` as a typed server operation and
returns `AckResult`.

```{tmuxop:operation} load_buffer
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import LoadBuffer, run
>>> operation = LoadBuffer(path="buffer.txt")
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

- {tmuxop:op}`list_windows`
- {tmuxop:op}`new_session`
