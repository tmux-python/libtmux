(experimental)=

# Experimental API

```{warning}
Everything under {mod}`libtmux.experimental` is **not** covered by the
versioning policy and may change or be removed between any two releases.
```

`libtmux.experimental` separates an inert, typed operation from the engine that
executes it. An operation renders tmux arguments and declares its result and
effects; an engine returns the raw command outcome, and
{func}`~libtmux.experimental.ops.run` or
{func}`~libtmux.experimental.ops.arun` converts it to the operation's typed
result.

## Start here

- [Operations](operations/index.md) documents every registered command by
  Server, Session, Window, Pane, and Client scope.
- [Results](results.md) documents shared status and output fields plus each
  operation payload type.
- [Engines](engines.md) explains how to choose a transport without changing the
  operation contract.
- [Plans](plans.md) covers deferred execution, planners, and the fluent builder.

## Run one operation

{func}`~libtmux.experimental.ops.run` passes an operation value to an engine.
Inspect the returned result, or opt into an exception with
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status`:

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import HasSession, run
>>> from libtmux.experimental.ops._types import SessionId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> result = run(HasSession(target=SessionId(session.session_id)), engine)
>>> result.status, result.exists
('complete', True)
>>> result.raise_for_status() is result
True
```

```{toctree}
:hidden:

operations/index
results
engines
plans
```
