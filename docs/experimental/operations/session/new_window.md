# Create a window in a session; capture the new window's id

`NewWindow` models `new-window` as a typed session operation and
returns `CreateResult`.

```{tmuxop:operation} new_window
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import NewWindow, run
>>> from libtmux.experimental.ops._types import SessionId
>>> operation = NewWindow(target=SessionId("$1"), name="build")
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

- {tmuxop:op}`kill_session`
- {tmuxop:op}`rename_session`
