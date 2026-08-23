# Build operation plans

A {class}`~libtmux.experimental.ops.plan.LazyPlan` records operations without
running them. Create operations return forward slot references, allowing later
operations to target objects that do not exist until execution.

## Record and execute

{meth}`~libtmux.experimental.ops.plan.LazyPlan.execute` resolves forward
references against captured identifiers as each operation completes. This live
plan creates a pane, queries its captured ID through the forward reference,
then removes it:

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import (
...     DisplayMessage,
...     KillPane,
...     LazyPlan,
...     SplitWindow,
...     WindowId,
... )
>>> assert window.window_id is not None
>>> operation_plan = LazyPlan()
>>> new_pane = operation_plan.add(
...     SplitWindow(target=WindowId(window.window_id)),
... )
>>> _ = operation_plan.add(
...     DisplayMessage(target=new_pane, message="#{pane_id}"),
... )
>>> _ = operation_plan.add(KillPane(target=new_pane))
>>> outcome = operation_plan.execute(
...     SubprocessEngine.for_server(server),
... ).raise_for_status()
>>> created_id = outcome.results[0].created_id
>>> created_id is not None
True
>>> outcome.results[1].text == created_id
True
>>> len(server.panes.filter(pane_id=created_id)) == 0
True
```

## Choose a planner

A {class}`~libtmux.experimental.ops.planner.Planner` turns a plan into
dispatches:

- {class}`~libtmux.experimental.ops.planner.SequentialPlanner` sends one
  dispatch per operation.
- {class}`~libtmux.experimental.ops.planner.FoldingPlanner` combines adjacent
  chainable operations.
- {class}`~libtmux.experimental.ops.planner.MarkedPlanner` folds creation and
  follow-up work by using tmux's `{marked}` register.

All planners preserve per-operation results. They differ only in dispatch
shape. The callback in this live example records the dispatches: two chainable
option writes fold, while the output-bearing read stays separate.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import (
...     FoldingPlanner,
...     LazyPlan,
...     SessionId,
...     SetOption,
...     ShowOptions,
... )
>>> assert session.session_id is not None
>>> target = SessionId(session.session_id)
>>> operation_plan = LazyPlan()
>>> _ = operation_plan.add(
...     SetOption(target=target, option="@docs_first", value="one"),
... )
>>> _ = operation_plan.add(
...     SetOption(target=target, option="@docs_second", value="two"),
... )
>>> _ = operation_plan.add(ShowOptions(target=target))
>>> steps = []
>>> outcome = operation_plan.execute(
...     SubprocessEngine.for_server(server),
...     planner=FoldingPlanner(),
...     on_step=lambda report: steps.append(report.step.indices),
... ).raise_for_status()
>>> steps
[(0, 1), (2,)]
>>> type(outcome.results[2]).__name__
'ShowOptionsResult'
>>> (
...     outcome.results[2].options["@docs_first"],
...     outcome.results[2].options["@docs_second"],
... )
('one', 'two')
```

## Build fluently

{func}`~libtmux.experimental.fluent.plan` records a hierarchy without requiring
the caller to thread newly created identifiers through each step. Nothing
touches tmux until {meth}`~libtmux.experimental.fluent.PlanBuilder.run`:

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.fluent import plan
>>> workspace_name = f"{session.session_name}-planned"
>>> workspace = plan()
>>> _ = workspace.new_session(workspace_name).new_window("logs")
>>> outcome = workspace.run(
...     SubprocessEngine.for_server(server),
... ).raise_for_status()
>>> outcome.ok, server.has_session(workspace_name)
(True, True)
>>> built = server.sessions.get(session_name=workspace_name)
>>> built is not None and len(built.windows) == 2
True
>>> _ = server.kill_session(workspace_name)
```

`split()` returns a forward handle so callers can continue composing work.
Execution records the handle's concrete pane identifier in
{attr}`~libtmux.experimental.ops.plan.PlanResult.bindings`.

See {doc}`tutorials/async-control-plans` to compose chainable operations, inspect
their compiled tmux sequence, and execute the plan over one persistent async
control-mode client.

## API reference

### Composition and references

```{eval-rst}
.. autoclass:: libtmux.experimental.ops.operation.Operation
   :members: then

.. autoclass:: libtmux.experimental.ops._chain.OpChain
   :members:

.. autoclass:: libtmux.experimental.ops._types.SlotRef
   :members:

.. autoclass:: libtmux.experimental.ops._types.PaneId
   :members:
```

### Plans and planners

```{eval-rst}
.. autoclass:: libtmux.experimental.ops.plan.LazyPlan
   :members:

.. autoclass:: libtmux.experimental.ops.plan.PlanResult
   :members:

.. autoclass:: libtmux.experimental.ops.planner.Planner
   :members:

.. autoclass:: libtmux.experimental.ops.planner.SequentialPlanner
   :members:

.. autoclass:: libtmux.experimental.ops.planner.FoldingPlanner
   :members:

.. autoclass:: libtmux.experimental.ops.planner.MarkedPlanner
   :members:

.. autoclass:: libtmux.experimental.ops.planner.BoundedPlanner
   :members:
```

### Fluent builder

```{eval-rst}
.. autofunction:: libtmux.experimental.fluent.plan

.. autoclass:: libtmux.experimental.fluent.PlanBuilder
   :members:

.. autoclass:: libtmux.experimental.fluent.SessionRef
   :members:

.. autoclass:: libtmux.experimental.fluent.WindowRef
   :members:
```
