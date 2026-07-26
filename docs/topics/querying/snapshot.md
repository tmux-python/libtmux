# Query pane snapshots and build commands

{func}`~libtmux.experimental.query.panes` starts an immutable
{class}`~libtmux.experimental.query.PaneQuery`. A query resolves against either
an engine or a supplied sequence of
{class}`~libtmux.experimental.models.snapshots.PaneSnapshot` values. It can
project reads or create a {class}`~libtmux.experimental.query.CommandPlan`.

## When to use it

Use snapshot queries when deterministic read composition matters, when one
captured view should drive several decisions, or when a bulk pane command
should be planned before dispatch. This API is experimental.

Calling `filter()`, `order_by()`, `limit()`, `map()`, or `commands()` is pure.
`all()` and `first()` resolve a source; `CommandPlan.run()` additionally
dispatches recorded operations.

## Tutorial

### Happy path

Resolve a pure query, then build one typed command per matching pane:

```python
>>> from libtmux.experimental.models.snapshots import PaneSnapshot
>>> from libtmux.experimental.query import panes
>>> rows = [
...     PaneSnapshot.from_format(
...         {"pane_id": "%1", "pane_active": "1", "pane_current_command": "vim"}
...     ),
...     PaneSnapshot.from_format(
...         {"pane_id": "%2", "pane_active": "0", "pane_current_command": "zsh"}
...     ),
... ]
>>> active = panes().filter(active=True)
>>> active.map(lambda item: item.pane_id).all(rows)
('%1',)
>>> commands = active.commands(lambda ref: ref.cmd.send_keys("clear"))
>>> [operation.kind for operation in commands.to_plan(rows).operations]
['send_keys']
```

### Sad path

An empty snapshot query is an ordinary value: `first()` returns `None`, and a
derived command plan contains no operations:

```python
>>> from libtmux.experimental.models.snapshots import PaneSnapshot
>>> from libtmux.experimental.query import panes
>>> rows = [
...     PaneSnapshot.from_format(
...         {"pane_id": "%1", "pane_active": "1", "pane_current_command": "zsh"}
...     )
... ]
>>> missing = panes().filter(current_command="vim")
>>> missing.first(rows) is None
True
>>> command_plan = missing.commands(lambda ref: ref.cmd.send_keys("clear"))
>>> len(command_plan.to_plan(rows).operations)
0
```

An empty query does not indicate a transport failure. When the source is an
engine, inspect the engine result path separately if failure provenance matters.

## API reference

```{eval-rst}
.. autofunction:: libtmux.experimental.query.panes

.. autoclass:: libtmux.experimental.query.PaneQuery
   :members: filter, order_by, limit, all, first, map, commands
   :no-undoc-members:

.. autoclass:: libtmux.experimental.query.CommandPlan
   :members: to_plan, run
   :no-undoc-members:
```

## Related topics

- [Experimental operations](../../experimental/operations/index.md) documents
  the commands produced by a command plan.
- [Experimental plans](../../experimental/plans.md) explains forward
  references and planner selection.
- [QueryList filtering](query-list.md) supplies the lookup language used by
  `PaneQuery.filter()`.
