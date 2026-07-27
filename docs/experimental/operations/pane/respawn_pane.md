# Restart a pane command

{class}`~libtmux.experimental.ops.RespawnPane` replaces the process running in
an existing pane while keeping the pane identifier.

## Example

This executable example uses the injected live `server` and `session` context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListPanes, NewWindow, RespawnPane, run
>>> from libtmux.experimental.ops._types import PaneId, SessionId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> created = run(
...     NewWindow(
...         target=SessionId(session.session_id),
...         name="docs-respawn-pane",
...         capture_pane=True,
...         window_shell="sleep 30",
...     ),
...     engine,
... ).raise_for_status()
>>> assert created.first_pane_id is not None
>>> target = PaneId(created.first_pane_id)
>>> before = run(ListPanes(), engine).raise_for_status()
>>> original = next(
...     item for item in before.panes if item.pane_id == created.first_pane_id
... )
>>> assert original.pid is not None
>>> result = run(
...     RespawnPane(target=target, kill=True, shell="sleep 30"),
...     engine,
... ).raise_for_status()
>>> after = run(ListPanes(), engine).raise_for_status()
>>> restarted = next(
...     item for item in after.panes if item.pane_id == created.first_pane_id
... )
>>> type(result).__name__, restarted.pane_id == original.pane_id, restarted.pid != original.pid
('AckResult', True, True)
```

## Operation reference

```{tmuxop:operation} respawn_pane
```

## Failure and effects

Use `kill=True` when the current process is still running. The optional
environment flag requires tmux 3.0 or newer.

The example creates the pane and process it replaces.

## Related operations

- {tmuxop:op}`resize_pane`
- {tmuxop:op}`select_pane`
