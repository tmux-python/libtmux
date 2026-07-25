# Send keys (input) to a pane

`SendKeys` models `send-keys` as a typed pane operation and
returns `AckResult`.

```{tmuxop:operation} send_keys
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import SendKeys, run
>>> from libtmux.experimental.ops._types import PaneId
>>> operation = SendKeys(target=PaneId("%1"), keys="echo ready", enter=True)
>>> result = run(operation, MockEngine())
>>> result.status
'complete'
```

## Failure and effects

This operation changes tmux state. It writes input.

`MockEngine` validates the command and result contract, but it does not prove
that a live target exists. A live engine reports an invalid or missing target
as a failed result; call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` to raise the
underlying error.

## Related operations

- {tmuxop:op}`select_pane`
- {tmuxop:op}`swap_pane`
