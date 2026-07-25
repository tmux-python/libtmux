# Join a source pane into a destination window/pane

`JoinPane` models `join-pane` as a typed pane operation and
returns `AckResult`.

```{tmuxop:operation} join_pane
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import JoinPane, run
>>> from libtmux.experimental.ops._types import PaneId, WindowId
>>> operation = JoinPane(target=WindowId("@1"), src_target=PaneId("%2"))
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

- {tmuxop:op}`display_message`
- {tmuxop:op}`kill_pane`
