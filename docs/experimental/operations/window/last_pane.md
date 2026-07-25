# Select the previously active pane in a window

`LastPane` models `last-pane` as a typed window operation and
returns `AckResult`.

```{tmuxop:operation} last_pane
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import LastPane, run
>>> from libtmux.experimental.ops._types import PaneId
>>> operation = LastPane(target=PaneId("%1"))
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

- {tmuxop:op}`kill_window`
- {tmuxop:op}`last_window`
