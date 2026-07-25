# Show the contents of a paste buffer

`ShowBuffer` models `show-buffer` as a typed server operation and
returns `ShowBufferResult`.

```{tmuxop:operation} show_buffer
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import ShowBuffer, run
>>> operation = ShowBuffer(buffer_name="build")
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

- {tmuxop:op}`set_buffer`
- {tmuxop:op}`source_file`
