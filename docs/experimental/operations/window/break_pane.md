# Break a pane out into a new window

{class}`~libtmux.experimental.ops.BreakPane` breaks a pane into a new window
and returns its identifier in a
{class}`~libtmux.experimental.ops.results.CreateResult`.

## Example

This executable example uses an isolated live tmux server. `server` and
`session` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import (
...     BreakPane,
...     ListWindows,
...     NewWindow,
...     SplitWindow,
...     run,
... )
>>> from libtmux.experimental.ops._types import PaneId, SessionId, WindowId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> owned = run(
...     NewWindow(target=SessionId(session.session_id), name="docs-break-source"),
...     engine,
... ).raise_for_status()
>>> assert owned.new_id is not None
>>> split = run(SplitWindow(target=WindowId(owned.new_id)), engine).raise_for_status()
>>> assert split.new_pane_id is not None
>>> broken = run(
...     BreakPane(src_target=PaneId(split.new_pane_id), name="docs-broken"),
...     engine,
... ).raise_for_status()
>>> assert broken.new_id is not None
>>> observed = run(ListWindows(), engine).raise_for_status()
>>> any(
...     item.window_id == broken.new_id
...     and item.session_id == session.session_id
...     and item.name == "docs-broken"
...     for item in observed.windows
... )
True
```

## Operation reference

```{tmuxop:operation} break_pane
```

## Failure and effects

This operation changes tmux state. It creates a window.

On exactly tmux 3.7, every request receives the placeholder `-n libtmux` to
avoid an upstream null dereference. tmux 3.7 also ignores the requested name,
so {func}`~libtmux.experimental.ops.run` and
{func}`~libtmux.experimental.ops.arun` apply it with a typed `rename-window`
follow-up. A failed follow-up makes the complete operation fail instead of
reporting a name that was not applied.

The captured identifier is resolved through
{class}`~libtmux.experimental.ops.ListWindows`; a non-`None` identifier alone
would not prove that tmux created the window.

## Related operations

- {tmuxop:op}`unlink_window`
- {tmuxop:op}`kill_window`
