# Kill a pane. Destructive; produces no output

`KillPane` models `kill-pane` as a typed pane operation and
returns `AckResult`.

```{tmuxop:operation} kill_pane
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import KillPane, run
>>> from libtmux.experimental.ops._types import PaneId
>>> operation = KillPane(target=PaneId("%1"))
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

- {tmuxop:op}`join_pane`
- {tmuxop:op}`move_pane`
