# Paste a buffer into a pane

`PasteBuffer` models `paste-buffer` as a typed pane operation and
returns `AckResult`.

```{tmuxop:operation} paste_buffer
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import PasteBuffer, run
>>> from libtmux.experimental.ops._types import PaneId
>>> operation = PasteBuffer(target=PaneId("%1"), buffer_name="build")
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

- {tmuxop:op}`move_pane`
- {tmuxop:op}`pipe_pane`
