# Check whether a session exists

`HasSession` models `has-session` as a typed session operation and
returns `HasSessionResult`.

```{tmuxop:operation} has_session
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import HasSession, run
>>> from libtmux.experimental.ops._types import SessionId
>>> operation = HasSession(target=SessionId("$1"))
>>> result = run(operation, MockEngine())
>>> result.status
'complete'
```

## Failure and effects

This operation reads tmux state without changing it. It is safe to repeat.

`MockEngine` validates the command and result contract, but it does not prove
that a live target exists. A live engine reports an invalid or missing target
as a failed result; call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` to raise the
underlying error.

## Related operations

- {tmuxop:op}`show_options`
- {tmuxop:op}`kill_session`
