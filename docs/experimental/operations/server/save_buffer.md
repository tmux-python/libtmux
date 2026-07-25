# Save a paste buffer to a file

`SaveBuffer` models `save-buffer` as a typed server operation and
returns `AckResult`.

```{tmuxop:operation} save_buffer
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import SaveBuffer, run
>>> operation = SaveBuffer(path="buffer.txt", buffer_name="build")
>>> result = run(operation, MockEngine())
>>> result.status
'complete'
```

## Failure and effects

This operation reads tmux state without changing it.

`MockEngine` validates the command and result contract, but it does not prove
that a live target exists. A live engine reports an invalid or missing target
as a failed result; call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` to raise the
underlying error.

## Related operations

- {tmuxop:op}`run_shell`
- {tmuxop:op}`set_buffer`
