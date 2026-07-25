# Create a floating pane

{class}`~libtmux.experimental.ops.NewPane` creates a floating pane on tmux 3.7
or newer and returns a
{class}`~libtmux.experimental.ops.results.SplitWindowResult`.

## Example

This executable example uses an isolated live tmux server. `server` and `pane`
are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import NewPane, VersionUnsupported, run
>>> from libtmux.experimental.ops._types import PaneId
>>> assert pane.pane_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> try:
...     result = run(
...         NewPane(target=PaneId(pane.pane_id), width=40, height=10),
...         engine,
...     ).raise_for_status()
... except VersionUnsupported as error:
...     proof = (
...         error.kind == "new_pane"
...         and error.need == "3.7"
...         and bool(error.have)
...     )
... else:
...     proof = (
...         result.new_pane_id is not None
...         and server.panes.get(pane_id=result.new_pane_id) is not None
...     )
>>> proof
True
```

## Operation reference

```{tmuxop:operation} new_pane
```

## Failure and effects

This operation changes tmux state. It creates a pane.

On tmux older than 3.7, rendering raises
{exc}`~libtmux.experimental.ops.VersionUnsupported` before dispatch. The same
doctest proves that exact gate on older CI jobs and resolves the new pane on
supported versions; it does not skip either branch.

## Related operations

- {tmuxop:op}`move_window`
- {tmuxop:op}`next_window`
