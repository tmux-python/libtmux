# Switch a client to a session. Produces no output

`SwitchClient` models `switch-client` as a typed client operation and
returns `AckResult`.

```{tmuxop:operation} switch_client
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import SwitchClient, run
>>> operation = SwitchClient(client="/dev/pts/3", to_session="$1")
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

- {tmuxop:op}`suspend_client`
- {tmuxop:op}`detach_client`
