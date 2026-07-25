# Resize a pane, optionally zooming it

`ResizePane` models `resize-pane` as a typed pane operation and
returns `AckResult`.

```{tmuxop:operation} resize_pane
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import ResizePane, run
>>> from libtmux.experimental.ops._types import PaneId
>>> operation = ResizePane(target=PaneId("%1"), height=20)
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

- {tmuxop:op}`pipe_pane`
- {tmuxop:op}`respawn_pane`
