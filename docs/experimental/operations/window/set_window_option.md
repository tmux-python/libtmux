# Set a window option

`SetWindowOption` models `set-window-option` as a typed window operation and
returns `AckResult`.

```{tmuxop:operation} set_window_option
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import SetWindowOption, run
>>> from libtmux.experimental.ops._types import WindowId
>>> operation = SetWindowOption(target=WindowId("@1"), option="mode-keys", value="vi")
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

- {tmuxop:op}`select_window`
- {tmuxop:op}`split_window`
