# Build operation plans

A {class}`~libtmux.experimental.ops.plan.LazyPlan` records operations without
running them. Create operations return forward slot references, allowing later
operations to target objects that do not exist until execution.

## Record and execute

{meth}`~libtmux.experimental.ops.plan.LazyPlan.execute` resolves forward
references against captured identifiers as each operation completes:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import LazyPlan, SendKeys, SplitWindow
>>> from libtmux.experimental.ops._types import WindowId
>>> operation_plan = LazyPlan()
>>> new_pane = operation_plan.add(SplitWindow(target=WindowId("@1")))
>>> _ = operation_plan.add(SendKeys(target=new_pane, keys="echo hi", enter=True))
>>> outcome = operation_plan.execute(MockEngine())
>>> [result.status for result in outcome.results]
['complete', 'complete']
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
shape:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import FoldingPlanner, LazyPlan, SendKeys, SplitWindow
>>> from libtmux.experimental.ops._types import WindowId
>>> operation_plan = LazyPlan()
>>> new_pane = operation_plan.add(SplitWindow(target=WindowId("@1")))
>>> _ = operation_plan.add(SendKeys(target=new_pane, keys="echo hi", enter=True))
>>> operation_plan.execute(MockEngine(), planner=FoldingPlanner()).ok
True
```

## Build fluently

{func}`~libtmux.experimental.fluent.plan` records a hierarchy without requiring
the caller to thread newly created identifiers through each step. Nothing
touches tmux until {meth}`~libtmux.experimental.fluent.PlanBuilder.run`:

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.fluent import plan
>>> workspace = plan()
>>> pane = workspace.new_session("dev").window().pane()
>>> _ = pane.do(lambda commands: commands.send_keys("vim"))
>>> workspace.run(MockEngine()).ok
True
```

`split()` returns a forward handle: callers can continue composing work, but
the handle gains a concrete pane identifier only when the plan executes.
