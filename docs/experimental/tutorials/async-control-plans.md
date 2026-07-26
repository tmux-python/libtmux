# Master async control-mode plans

Build a typed operation plan synchronously, then execute it asynchronously over
one persistent tmux client. The useful mental model has three distinct layers:

| Layer | Owns | Does not imply |
| --- | --- | --- |
| Python composition | Operation order and forward references | Any tmux I/O |
| Planning | Which operations share one tmux command sequence | Process reuse |
| Control mode | One persistent `tmux -C` client and framed replies | One reply per plan |

Keeping those layers separate lets you change dispatch policy or transport
without rewriting the operations.

## Compose and run one live plan

This plan creates a pane, assigns two pane-local user options, then reads them
back. The pane does not exist when Python records the option operations, so
{meth}`~libtmux.experimental.ops.plan.LazyPlan.add` returns a
{class}`~libtmux.experimental.ops._types.SlotRef` that stands in for its future
ID.

The two tabs show the same work at the Python and tmux boundaries. `@WINDOW`
stands for the live window ID. `%PANE` stands for the pane ID captured by
`split-window`.

`````{tab} Python plan
```python
>>> import asyncio
>>> from libtmux.experimental.engines import AsyncControlModeEngine
>>> from libtmux.experimental.ops import (
...     DisplayMessage,
...     LazyPlan,
...     MarkedPlanner,
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
...     for step in operation_plan.explain(MarkedPlanner())
... ]
[(('split_window', 'set_option', 'set_option'), 'marked-fold'),
 (('display_message',), 'capture')]
>>> async def configure_worker():
...     async with AsyncControlModeEngine.for_server(server) as engine:
...         return await operation_plan.aexecute(
...             engine,
...             planner=MarkedPlanner(),
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

`````{tab} Compiled tmux sequence
The pane creation and its two decorations compile into one tmux command
sequence:

```console
$ tmux split-window \
    -t @WINDOW \
    -v \
    -P \
    -F '#{pane_id}' \
    \; select-pane -m \
    \; set-option -t '{marked}' -p -- @role worker \
    \; set-option -t '{marked}' -p -- @state ready \
    \; select-pane -M
```

After tmux returns the new pane ID, the output-bearing query becomes a second
dispatch:

```console
$ tmux display-message \
    -t %PANE \
    -p \
    -- '#{@role}:#{@state}'
```
`````

These console commands are the direct-CLI equivalents. The control-mode engine
does not start `tmux` for either line. It removes the leading executable and
writes each command sequence to the standard input of the existing `tmux -C`
client.

## Layer one: compose Python values

{meth}`~libtmux.experimental.ops.operation.Operation.then` and `>>` create an
ordered {class}`~libtmux.experimental.ops._chain.OpChain`.
{meth}`~libtmux.experimental.ops.plan.LazyPlan.add_chain` records that order in
the plan. Both operations are inert: they neither contact tmux nor promise that
the operations will share a dispatch.

That distinction matters because
{meth}`~libtmux.experimental.ops.plan.LazyPlan.aexecute` defaults to
{class}`~libtmux.experimental.ops.planner.SequentialPlanner`. Pass a folding
planner explicitly when dispatch shape matters.

## Layer two: fold safe tmux sequences

{class}`~libtmux.experimental.ops.planner.MarkedPlanner` recognizes a focused
pane creator followed immediately by chainable operations targeting that
creator's exact forward reference. It emits:

1. `split-window -P -F '#{pane_id}'`;
2. `select-pane -m` to mark the newly focused pane;
3. each decoration retargeted to tmux's `{marked}` special target; and
4. `select-pane -M` to clear the mark.

The first planner step therefore contains three user operations but becomes one
engine request. The mark and unmark commands are implementation details and do
not add operation results.

The final
{class}`~libtmux.experimental.ops._ops.display_message.DisplayMessage` remains
separate because it produces output. Combining its stdout with the creator's
captured pane ID would make typed result attribution ambiguous. Creators,
capturing reads, and any operation declaring `chainable = False` remain hard
boundaries unless a specialized planner has a safe attribution rule.

## Resolve references at the last responsible moment

The worker target passes through three representations:

1. Python records `SlotRef(slot=0)` before a pane exists.
2. The marked fold addresses the new pane as `{marked}` inside one tmux
   sequence.
3. The captured `%N` binds slot `0`; subsequent operations render a concrete
   {class}`~libtmux.experimental.ops._types.PaneId`.

The plan awaits each planner step before rendering a dependent step. That is why
the `display-message` request contains `%PANE`, while the two option writes can
run earlier against `{marked}`.

## Reuse one asynchronous transport

{class}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine`
owns one long-lived `tmux -C attach-session -E` child while its async context is
open. Each planner step becomes one newline-terminated control-mode request.
Tmux frames every subcommand reply with `%begin` and `%end` or `%error`; the
engine correlates those blocks into raw command results, and the plan maps the
raw outcomes back to typed operation results.

This example has four operations and two planner steps, but only one persistent
control client process. Control mode avoids one process start per request; it
does not eliminate processes entirely.

Use
{meth}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine.run_batch`
for independent, already-rendered requests. A forward-reference plan cannot
pipeline dependent steps that way because it must capture the first result
before it can render the next target.

## Know the boundaries

- Enter the async context only after a safe session exists. Without an
  attachable session, the engine uses async subprocess execution to bootstrap
  the server.
- Keep output-bearing reads and failure-sensitive validation in their own
  planner steps. Tmux stops a command sequence after an error, and a folded
  result cannot provide independent stdout or exact failure attribution for
  every subcommand.
- A detached pane creator cannot use the marked-pane optimization because it
  does not focus the new pane.
- Host-side waits, sleeps, or callbacks are dispatch boundaries. Use a bounded
  planner when host work must occur between operations.
- Scope the engine with `async with` so its reader, supervisor, and control
  client close before the event loop exits.

See {doc}`control-mode` for attachment, notification, and reconnection
lifecycle details. See {doc}`results-and-failures` for typed command failures
and skipped work.
