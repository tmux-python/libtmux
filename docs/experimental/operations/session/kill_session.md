# Kill a session. Destructive; produces no output

`KillSession` models `kill-session` as a typed session operation and
returns `AckResult`.

```{tmuxop:operation} kill_session
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import KillSession, run
>>> from libtmux.experimental.ops._types import SessionId
>>> operation = KillSession(target=SessionId("$1"))
>>> result = run(operation, MockEngine())
>>> result.status
'complete'
```

## Failure and effects

This operation is destructive and cannot be undone.

`MockEngine` validates the command and result contract, but it does not prove
that a live target exists. A live engine reports an invalid or missing target
as a failed result; call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` to raise the
underlying error.

## Related operations

- {tmuxop:op}`has_session`
- {tmuxop:op}`new_window`
