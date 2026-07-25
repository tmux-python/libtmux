# Apply a layout to a window

`SelectLayout` models `select-layout` as a typed window operation and
returns `AckResult`.

```{tmuxop:operation} select_layout
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import SelectLayout, run
>>> from libtmux.experimental.ops._types import WindowId
>>> operation = SelectLayout(target=WindowId("@1"), layout="even-horizontal")
>>> result = run(operation, MockEngine())
>>> result.status
'complete'
```

## Failure and effects

This operation changes tmux state. It changes layout, is safe to repeat.

`MockEngine` validates the command and result contract, but it does not prove
that a live target exists. A live engine reports an invalid or missing target
as a failed result; call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` to raise the
underlying error.

## Related operations

- {tmuxop:op}`rotate_window`
- {tmuxop:op}`select_window`
