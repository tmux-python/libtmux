# Break a pane out into a new window

`BreakPane` models `break-pane` as a typed window operation and
returns `CreateResult`.

```{tmuxop:operation} break_pane
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import BreakPane, run
>>> from libtmux.experimental.ops._types import PaneId
>>> operation = BreakPane(src_target=PaneId("%2"))
>>> result = run(operation, MockEngine())
>>> result.status
'complete'
```

## Failure and effects

This operation changes tmux state. It creates a window.

`MockEngine` validates the command and result contract, but it does not prove
that a live target exists. A live engine reports an invalid or missing target
as a failed result; call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` to raise the
underlying error.

## Related operations

- {tmuxop:op}`unlink_window`
- {tmuxop:op}`kill_window`
