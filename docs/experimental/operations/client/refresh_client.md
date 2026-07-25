# Refresh a client. Produces no output

`RefreshClient` models `refresh-client` as a typed client operation and
returns `AckResult`.

```{tmuxop:operation} refresh_client
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import RefreshClient, run
>>> from libtmux.experimental.ops._types import ClientName
>>> operation = RefreshClient(target=ClientName("/dev/pts/3"))
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

- {tmuxop:op}`detach_client`
- {tmuxop:op}`suspend_client`
