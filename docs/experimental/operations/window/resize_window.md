# Resize a window

`ResizeWindow` models `resize-window` as a typed window operation and
returns `AckResult`.

```{tmuxop:operation} resize_window
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import ResizeWindow, run
>>> from libtmux.experimental.ops._types import WindowId
>>> operation = ResizeWindow(target=WindowId("@1"), width=100)
>>> result = run(operation, MockEngine())
>>> result.status
'complete'
```

## Failure and effects

This operation changes tmux state. It changes layout.

`MockEngine` validates the command and result contract, but it does not prove
that a live target exists. A live engine reports an invalid or missing target
as a failed result; call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` to raise the
underlying error.

## Related operations

- {tmuxop:op}`rename_window`
- {tmuxop:op}`respawn_window`
