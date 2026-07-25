# Move a window to a new index/session

`MoveWindow` models `move-window` as a typed window operation and
returns `AckResult`.

```{tmuxop:operation} move_window
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import MoveWindow, run
>>> from libtmux.experimental.ops._types import SessionId, WindowId
>>> operation = MoveWindow(target=SessionId("$1"), src_target=WindowId("@2"))
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

- {tmuxop:op}`link_window`
- {tmuxop:op}`new_pane`
