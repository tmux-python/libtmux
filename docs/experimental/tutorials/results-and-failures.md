# Handle results and failures

{func}`~libtmux.experimental.ops.run` returns the operation's declared
{class}`~libtmux.experimental.ops.results.Result` subtype. It does not collapse
successful payloads, command rejections, expected absence, render-time version
errors, and undispatched work into one exception path.

## Read a typed success

List operations retain raw output and expose typed projections over parsed
rows.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListSessions, result_to_dict, run
>>> assert session.session_id is not None
>>> result = run(
...     ListSessions(),
...     SubprocessEngine.for_server(server),
... ).raise_for_status()
>>> type(result).__name__, result.status
('ListSessionsResult', 'complete')
>>> any(item.session_id == session.session_id for item in result.sessions)
True
>>> payload = result_to_dict(result)
>>> payload["status"], len(payload["rows"]) == len(result.sessions)
('complete', True)
```

## Keep a tmux rejection as data

A rejected tmux command produces a failed result. Inspect it directly, or opt
into {exc}`~libtmux.experimental.ops.exc.TmuxCommandError` with
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status`.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import RenameWindow, TmuxCommandError, run
>>> from libtmux.experimental.ops._types import WindowId
>>> failed = run(
...     RenameWindow(target=WindowId("@999999999"), name="unreachable"),
...     SubprocessEngine.for_server(server),
... )
>>> failed.status, failed.returncode != 0, bool(failed.stderr)
('failed', True, True)
>>> try:
...     failed.raise_for_status()
... except TmuxCommandError as error:
...     details = (
...         error.returncode == failed.returncode,
...         error.cmd == failed.argv,
...     )
>>> details
(True, True)
```

## Treat expected absence as an answer

{class}`~libtmux.experimental.ops.HasSession` maps tmux's missing-session exit
to a complete {class}`~libtmux.experimental.ops.results.HasSessionResult`.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import HasSession, run
>>> from libtmux.experimental.ops._types import SessionId
>>> result = run(
...     HasSession(target=SessionId("$999999999")),
...     SubprocessEngine.for_server(server),
... )
>>> result.status, result.exists, result.returncode != 0
('complete', False, True)
>>> result.raise_for_status() is result
True
```

## Reject an unsupported operation before dispatch

Whole-operation version gates raise
{exc}`~libtmux.experimental.ops.exc.VersionUnsupported` while rendering. No
engine is called.

```python
>>> from libtmux.experimental.ops import NewPane, VersionUnsupported
>>> from libtmux.experimental.ops._types import PaneId
>>> try:
...     NewPane(target=PaneId("%1")).render(version="3.6")
... except VersionUnsupported as error:
...     requirement = (error.kind, error.need, error.have)
>>> requirement
('new_pane', '3.7', '3.6')
```

## Reject a successful create without a captured ID

Eager and async object navigation requires the identifier promised by a create
operation. If an engine reports success but omits that capture,
{exc}`~libtmux.experimental.ops.exc.MissingCreateIdError` preserves the complete
result for diagnosis instead of constructing an object with an empty target.

```python
>>> from libtmux.experimental.ops import MissingCreateIdError, NewSession
>>> missing = NewSession().build_result(returncode=0)
>>> try:
...     raise MissingCreateIdError(missing)
... except MissingCreateIdError as error:
...     details = (error.kind, error.missing, error.result is missing)
>>> details
('new_session', ('self',), True)
```

## Distinguish failed and skipped plan steps

A folding planner dispatches adjacent chainable operations as one tmux command
group. If the first command fails, tmux does not run the remainder; the result
attribution marks that remainder `skipped`.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import FoldingPlanner, LazyPlan, RenameWindow
>>> from libtmux.experimental.ops._types import WindowId
>>> assert window.window_id is not None
>>> plan = LazyPlan()
>>> _ = plan.add(
...     RenameWindow(target=WindowId("@999999999"), name="unreachable")
... )
>>> _ = plan.add(
...     RenameWindow(target=WindowId(window.window_id), name="not-applied")
... )
>>> outcome = plan.execute(
...     SubprocessEngine.for_server(server),
...     planner=FoldingPlanner(),
... )
>>> [result.status for result in outcome.results]
['failed', 'skipped']
```

With the default sequential planner, each step is a separate dispatch, so one
failed result does not by itself imply that the next operation was skipped.
