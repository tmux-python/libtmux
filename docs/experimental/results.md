# Results

Every operation returns an immutable
{class}`~libtmux.experimental.ops.results.Result` subtype. You inspect the same
status and tmux output fields for every command, then use the subtype's payload
when the command returns structured data. Most callers need only that contract
and {meth}`~libtmux.experimental.ops.results.Result.raise_for_status`.

## Read one result

{func}`~libtmux.experimental.ops.run` preserves a tmux rejection as result data.
Call {meth}`~libtmux.experimental.ops.results.Result.raise_for_status` where
your application wants a failed or unknown status to become an exception.
Successful list operations add typed snapshot views, such as
{attr}`~libtmux.experimental.ops.results.ListSessionsResult.sessions`.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListSessions, run
>>> assert session.session_id is not None
>>> result = run(
...     ListSessions(),
...     SubprocessEngine.for_server(server),
... ).raise_for_status()
>>> type(result).__name__, result.status, result.ok
('ListSessionsResult', 'complete', True)
>>> any(item.session_id == session.session_id for item in result.sessions)
True
```

All results retain the operation, rendered `argv`, `status`, `returncode`,
`stdout`, and `stderr`. `ok` is true only for `complete`; `failed` identifies a
tmux rejection or an incomplete composed operation.
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` raises for
`failed` and `unknown`, but returns both `complete` and `skipped` results. See
{doc}`tutorials/results-and-failures` for those paths in context.

## Choose the payload

- {class}`~libtmux.experimental.ops.results.AckResult` adds no payload; the
  status is the acknowledgement.
- {class}`~libtmux.experimental.ops.results.CreateResult` captures a created
  session or window and optional child IDs.
- {class}`~libtmux.experimental.ops.results.SplitWindowResult` captures a
  created pane ID.
- {class}`~libtmux.experimental.ops.results.CapturePaneResult`,
  {class}`~libtmux.experimental.ops.results.DisplayMessageResult`, and
  {class}`~libtmux.experimental.ops.results.ShowBufferResult` expose captured
  text.
- {class}`~libtmux.experimental.ops.results.HasSessionResult` turns expected
  absence into the boolean `exists` payload.
- {class}`~libtmux.experimental.ops.results.ShowOptionsResult` exposes parsed
  option values.
- {class}`~libtmux.experimental.ops.results.ListClientsResult`,
  {class}`~libtmux.experimental.ops.results.ListPanesResult`,
  {class}`~libtmux.experimental.ops.results.ListSessionsResult`, and
  {class}`~libtmux.experimental.ops.results.ListWindowsResult` expose typed
  snapshots over their parsed rows.

## API reference

### Shared contract

```{eval-rst}
.. autoclass:: libtmux.experimental.ops.results.Result
   :members:
```

### Acknowledgement and creation

```{eval-rst}
.. autoclass:: libtmux.experimental.ops.results.AckResult
   :members:

.. autoclass:: libtmux.experimental.ops.results.CreateResult
   :members:

.. autoclass:: libtmux.experimental.ops.results.SplitWindowResult
   :members:
```

### Text, existence, and options

```{eval-rst}
.. autoclass:: libtmux.experimental.ops.results.CapturePaneResult
   :members:

.. autoclass:: libtmux.experimental.ops.results.DisplayMessageResult
   :members:

.. autoclass:: libtmux.experimental.ops.results.HasSessionResult
   :members:

.. autoclass:: libtmux.experimental.ops.results.ShowBufferResult
   :members:

.. autoclass:: libtmux.experimental.ops.results.ShowOptionsResult
   :members:
```

### Snapshot collections

```{eval-rst}
.. autoclass:: libtmux.experimental.ops.results.ListClientsResult
   :members:

.. autoclass:: libtmux.experimental.ops.results.ListPanesResult
   :members:

.. autoclass:: libtmux.experimental.ops.results.ListSessionsResult
   :members:

.. autoclass:: libtmux.experimental.ops.results.ListWindowsResult
   :members:
```

### Navigation failures

```{eval-rst}
.. autoexception:: libtmux.experimental.ops.exc.MissingCreateIdError
```
