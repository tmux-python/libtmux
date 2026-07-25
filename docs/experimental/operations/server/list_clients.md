# List attached clients and return typed snapshots

`ListClients` models `list-clients` as a typed server operation and
returns `ListClientsResult`.

```{tmuxop:operation} list_clients
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import ListClients, run
>>> operation = ListClients()
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

- {tmuxop:op}`kill_server`
- {tmuxop:op}`list_panes`
