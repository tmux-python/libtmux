# Create a detached session; capture the new session's id

`NewSession` models `new-session` as a typed server operation and
returns `CreateResult`.

```{tmuxop:operation} new_session
```

## Example

This example executes the typed operation against the deterministic mock engine:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import NewSession, run
>>> operation = NewSession(session_name="build")
>>> result = run(operation, MockEngine())
>>> result.status
'complete'
```

## Failure and effects

This operation changes tmux state. It creates a session.

`MockEngine` validates the command and result contract, but it does not prove
that a live target exists. A live engine reports an invalid or missing target
as a failed result; call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` to raise the
underlying error.

## Related operations

- {tmuxop:op}`load_buffer`
- {tmuxop:op}`run_shell`
