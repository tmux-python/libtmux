# Clear a pane's scrollback history

{class}`~libtmux.experimental.ops.ClearHistory` discards a pane's accumulated
scrollback without closing the pane.

## Example

This executable example uses the injected live `server` and `session` context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import (
...     ClearHistory,
...     DisplayMessage,
...     NewWindow,
...     SendKeys,
...     run,
... )
>>> from libtmux.experimental.ops._types import PaneId, SessionId
>>> assert session.session_id is not None
>>> engine = SubprocessEngine.for_server(server)
>>> created = run(
...     NewWindow(
...         target=SessionId(session.session_id),
...         name="docs-clear-history",
...         capture_pane=True,
...     ),
...     engine,
... ).raise_for_status()
>>> assert created.first_pane_id is not None
>>> target = PaneId(created.first_pane_id)
>>> _ = run(
...     SendKeys(
...         target=target,
...         keys=(
...             "for i in $(seq 1 50); do echo docs-history-$i; done; "
...             "tmux wait-for -S docs-history"
...         ),
...         enter=True,
...     ),
...     engine,
... ).raise_for_status()
>>> server.wait_for("docs-history")
>>> before = run(
...     DisplayMessage(target=target, message="#{history_size}"),
...     engine,
... ).raise_for_status()
>>> result = run(ClearHistory(target=target), engine).raise_for_status()
>>> after = run(
...     DisplayMessage(target=target, message="#{history_size}"),
...     engine,
... ).raise_for_status()
>>> int(before.text) > 0, type(result).__name__, after.text
(True, 'AckResult', '0')
```

## Operation reference

```{tmuxop:operation} clear_history
```

## Failure and effects

Clearing scrollback is irreversible for that pane. It does not erase the lines
currently visible on screen, and repeating the operation is safe.

The example creates the pane whose history it clears.

## Related operations

- {tmuxop:op}`capture_pane`
- {tmuxop:op}`display_message`
