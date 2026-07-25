# Detach a client. Produces no output

`DetachClient` models `detach-client` as a typed client operation and
returns `AckResult`.

```{tmuxop:operation} detach_client
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import DetachClient, run
>>> from libtmux.experimental.ops._types import ClientName
>>> operation = DetachClient(target=ClientName("/dev/pts/3"))
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

- {tmuxop:op}`switch_client`
- {tmuxop:op}`refresh_client`
