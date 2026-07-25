# Start the tmux server if it is not already running

`StartServer` models `start-server` as a typed server operation and
returns `AckResult`.

```{tmuxop:operation} start_server
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import StartServer, run
>>> operation = StartServer()
>>> result = run(operation, MockEngine())
>>> result.status
'complete'
```

## Failure and effects

This operation changes tmux state. It is safe to repeat.

`MockEngine` validates the command and result contract, but it does not prove
that a live target exists. A live engine reports an invalid or missing target
as a failed result; call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` to raise the
underlying error.

## Related operations

- {tmuxop:op}`source_file`
- {tmuxop:op}`delete_buffer`
