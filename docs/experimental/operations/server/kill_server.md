# Kill the tmux server and all its sessions

`KillServer` models `kill-server` as a typed server operation and
returns `AckResult`.

```{tmuxop:operation} kill_server
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import KillServer, run
>>> operation = KillServer()
>>> result = run(operation, MockEngine())
>>> result.status
'complete'
```

## Failure and effects

This operation is destructive and cannot be undone.

`MockEngine` validates the command and result contract, but it does not prove
that a live target exists. A live engine reports an invalid or missing target
as a failed result; call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` to raise the
underlying error.

## Related operations

- {tmuxop:op}`delete_buffer`
- {tmuxop:op}`list_clients`
