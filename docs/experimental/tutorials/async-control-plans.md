# Async control-mode plans

Build a typed operation plan synchronously, then execute it asynchronously over
one persistent tmux client. Keep three layers distinct:

| Layer | Owns | Does not imply |
| --- | --- | --- |
| Python composition | Operation order and forward references | Any tmux I/O |
| Planning | Which ready requests share an execution step | Merged commands or results |
| Control mode | One persistent `tmux -C` client and framed replies | One request per step |

This separation lets the same plan run through subprocess or control mode
without changing its result semantics.

## Compose and run one live plan

This plan creates a pane, assigns two pane-local user options, then reads them
back. The pane does not exist when Python records the later operations, so
{meth}`~libtmux.experimental.ops.plan.LazyPlan.add` returns a
{class}`~libtmux.experimental.ops._types.SlotRef` for its future ID.

The workflow has three explicit phases:

- Observe: preview unresolved arguments and explain the two planner steps
  without contacting tmux.
- Act: execute through
  {class}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine`.
- Verify: inspect four typed results, the captured `worker:ready` value, and the
  live pane lookup.

`````{tab} Python plan
```python
>>> import asyncio
>>> from libtmux.experimental.engines import AsyncControlModeEngine
>>> from libtmux.experimental.ops import (
...     BatchingPlanner,
...     DisplayMessage,
...     LazyPlan,
...     PaneId,
...     SetOption,
...     SplitWindow,
...     WindowId,
... )
>>> assert window.window_id is not None
>>> operation_plan = LazyPlan()
>>> worker = operation_plan.add(
...     SplitWindow(target=WindowId(window.window_id)),
... )
>>> worker
SlotRef(slot=0, suffix='', part='self')
>>> operation_plan.add_chain(
...     SetOption(
...         target=worker,
...         pane=True,
...         option="@role",
...         value="worker",
...     )
...     >> SetOption(
...         target=worker,
...         pane=True,
...         option="@state",
...         value="ready",
...     ),
... )
>>> _ = operation_plan.add(
...     DisplayMessage(
...         target=worker,
...         message="#{@role}:#{@state}",
...     ),
... )
>>> operation_plan.preview()[1:]
[None, None, None]
>>> [
...     (step.kinds, step.reason)
...     for step in operation_plan.explain(BatchingPlanner())
... ]
[(('split_window',), 'creator'),
 (('set_option', 'set_option', 'display_message'), 'batch')]
>>> async def configure_worker():
...     async with AsyncControlModeEngine.for_server(server) as engine:
...         return await operation_plan.aexecute(
...             engine,
...             planner=BatchingPlanner(),
...         )
>>> outcome = asyncio.run(configure_worker())
>>> [result.status for result in outcome.results]
['complete', 'complete', 'complete', 'complete']
>>> pane_id = outcome.bindings[worker.slot]
>>> outcome.results[1].operation.target == PaneId(pane_id)
True
>>> outcome.results[-1].text
'worker:ready'
>>> server.panes.get(pane_id=pane_id) is not None
True
```
`````

`````{tab} Tmux requests
The creator is the first planner step because its captured ID must bind before
the other requests can render:

```console
$ tmux split-window \
    -t @WINDOW \
    -v \
    -P \
    -F '#{pane_id}'
```

After `%PANE` binds, the second planner step contains three distinct requests:

```console
$ tmux set-option \
    -t %PANE \
    -p \
    -- @role worker
```

```console
$ tmux set-option \
    -t %PANE \
    -p \
    -- @state ready
```

```console
$ tmux display-message \
    -t %PANE \
    -p \
    -- '#{@role}:#{@state}'
```
`````

These are direct-CLI equivalents. The control-mode engine removes the leading
executable and writes each command as its own newline-terminated request to the
existing `tmux -C` client. It never joins them with `;`.

## Layer one: compose Python values

{meth}`~libtmux.experimental.ops.operation.Operation.then` and `>>` create an
ordered {class}`~libtmux.experimental.ops._chain.OpChain`.
{meth}`~libtmux.experimental.ops.plan.LazyPlan.add_chain` records that order.
Composition is inert: it neither contacts tmux nor promises one transport
request.

{meth}`~libtmux.experimental.ops.plan.LazyPlan.aexecute` defaults to
{class}`~libtmux.experimental.ops.planner.SequentialPlanner`. Pass
{class}`~libtmux.experimental.ops.planner.BatchingPlanner` when ready requests
should share a planner step.

## Layer two: batch ready requests

{class}`~libtmux.experimental.ops.planner.BatchingPlanner` groups adjacent
primitive operations whose arguments are ready to render. Every operation still
becomes one {class}`~libtmux.engines.base.CommandRequest` and one
typed result. A creator remains its own step when later requests need its
captured ID.

The plan validates custom planner output before dispatch: steps must form an
exact ordered partition, and a batch cannot contain an ensured, composite, or
non-batchable operation. The engine must return exactly one result per request.

## Resolve references at the last responsible moment

The worker target has two representations:

1. Python records `SlotRef(slot=0)` before a pane exists.
2. The creator returns `%N`; slot `0` binds, and the second step renders three
   concrete {class}`~libtmux.experimental.ops._types.PaneId` targets.

The plan awaits the creator step before rendering the batch. It does not borrow
tmux's server-global marked-pane register, so an existing user mark remains
untouched on both success and failure.

## Reuse one asynchronous transport

{class}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine`
owns one long-lived `tmux -C attach-session -E` child while its async context is
open. The example has four operations, two planner steps, four tmux requests,
and one persistent client process.

{meth}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine.run_batch`
writes the three ready requests without waiting between writes. Tmux frames each
reply with `%begin` and `%end` or `%error`; the engine correlates each frame to
its request, and the plan builds the corresponding typed result. A failed
request does not abort later requests in the batch.

Subprocess engines use the same batch contract but still start one process per
request. Batching changes semantics only when a transport can pipeline; it does
not claim a subprocess speedup.

## Know the boundaries

- Enter the async context only after a safe session exists. Without an
  attachable session, the engine uses async subprocess execution to bootstrap
  the server.
- A forward-reference dependency ends a batch because the next target cannot
  render until the creator result arrives.
- Host-side waits, sleeps, or callbacks are planner-step boundaries. Use a
  {class}`~libtmux.experimental.ops.planner.BoundedPlanner` when host work must
  occur between operations.
- A typed {class}`~libtmux.experimental.engines.base.CommandSeparator` creates a
  deliberate tmux fail-stop command group inside one raw request. It is not a
  request batch and cannot provide per-command attribution through subprocess.
- Scope the engine with `async with` so its reader, supervisor, and control
  client close before the event loop exits.

See {doc}`../engines/async-control-mode` for attachment, notification, and
reconnection lifecycle details. See {doc}`results-and-failures` for typed
command failures and continuation.
