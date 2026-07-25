# Rename a session. Produces no output

`RenameSession` models `rename-session` as a typed session operation and
returns `AckResult`.

```{tmuxop:operation} rename_session
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import RenameSession, run
>>> from libtmux.experimental.ops._types import SessionId
>>> operation = RenameSession(target=SessionId("$1"), name="build")
>>> result = run(operation, MockEngine())
>>> result.status
'complete'
```

## Failure and effects

This operation changes tmux state. It is safe to repeat.

`MockEngine` validates the command and result contract, but it does not prove
that a live target exists. A live engine reports an invalid or missing target
as a failed result; call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` to raise the
underlying error.

## Related operations

- {tmuxop:op}`new_window`
- {tmuxop:op}`set_environment`
