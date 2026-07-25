# Clear a pane's scrollback history

`ClearHistory` models `clear-history` as a typed pane operation and
returns `AckResult`.

```{tmuxop:operation} clear_history
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import ClearHistory, run
>>> from libtmux.experimental.ops._types import PaneId
>>> operation = ClearHistory(target=PaneId("%1"))
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

- {tmuxop:op}`capture_pane`
- {tmuxop:op}`display_message`
