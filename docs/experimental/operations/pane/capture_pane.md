# Capture a pane's contents

`CapturePane` models `capture-pane` as a typed pane operation and
returns `CapturePaneResult`.

```{tmuxop:operation} capture_pane
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import CapturePane, run
>>> from libtmux.experimental.ops._types import PaneId
>>> operation = CapturePane(target=PaneId("%1"))
>>> result = run(operation, MockEngine())
>>> result.status
'complete'
```

## Failure and effects

This operation reads tmux state without changing it. It reads command output, is safe to repeat.

`MockEngine` validates the command and result contract, but it does not prove
that a live target exists. A live engine reports an invalid or missing target
as a failed result; call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` to raise the
underlying error.

## Related operations

- {tmuxop:op}`swap_pane`
- {tmuxop:op}`clear_history`
