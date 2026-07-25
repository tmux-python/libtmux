# Evaluate a tmux format and print it

`DisplayMessage` models `display-message` as a typed pane operation and
returns `DisplayMessageResult`.

```{tmuxop:operation} display_message
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import DisplayMessage, run
>>> from libtmux.experimental.ops._types import PaneId
>>> operation = DisplayMessage(target=PaneId("%1"), message="#{pane_id}")
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

- {tmuxop:op}`clear_history`
- {tmuxop:op}`join_pane`
