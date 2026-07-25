# Pipe a pane's output to a shell command

`PipePane` models `pipe-pane` as a typed pane operation and
returns `AckResult`.

```{tmuxop:operation} pipe_pane
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import PipePane, run
>>> from libtmux.experimental.ops._types import PaneId
>>> operation = PipePane(target=PaneId("%1"), command_line="tee pane.log")
>>> result = run(operation, MockEngine())
>>> result.status
'complete'
```

## Failure and effects

This operation changes tmux state. It reads command output.

`MockEngine` validates the command and result contract, but it does not prove
that a live target exists. A live engine reports an invalid or missing target
as a failed result; call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` to raise the
underlying error.

## Related operations

- {tmuxop:op}`paste_buffer`
- {tmuxop:op}`resize_pane`
