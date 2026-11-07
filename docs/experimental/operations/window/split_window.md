# Split a pane, creating a new pane

{class}`~libtmux.experimental.ops.SplitWindow` adds a tiled pane and returns
its identifier in a
{class}`~libtmux.experimental.ops.results.SplitWindowResult`.

## Example

This executable example uses an isolated live tmux server. `server` and
`session` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListPanes, NewWindow, SplitWindow, run
>>> from libtmux.experimental.ops._types import SessionId, WindowId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> created = run(
...     NewWindow(target=SessionId(session.session_id), name="docs-split"),
...     engine,
... ).raise_for_status()
>>> assert created.new_id is not None
>>> split = run(
...     SplitWindow(target=WindowId(created.new_id)),
...     engine,
... ).raise_for_status()
>>> assert split.new_pane_id is not None
>>> observed = run(ListPanes(), engine).raise_for_status()
>>> any(
...     item.pane_id == split.new_pane_id
...     and item.window_id == created.new_id
...     for item in observed.panes
... )
True
```

## Operation reference

```{tmuxop:operation} split_window
```

## Failure and effects

This operation changes tmux state. It creates a pane.

The example resolves the captured pane identifier through
{class}`~libtmux.experimental.ops.ListPanes` and verifies that it belongs to the
owned window.

## Related operations

- {tmuxop:op}`set_window_option`
- {tmuxop:op}`swap_window`
