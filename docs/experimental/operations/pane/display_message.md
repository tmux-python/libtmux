# Evaluate a tmux format

{class}`~libtmux.experimental.ops.DisplayMessage` evaluates a tmux format
against a target and returns its text.

## Example

This executable example uses the injected live `server`, `session`, `window`,
and `pane` context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import DisplayMessage, run
>>> from libtmux.experimental.ops._types import PaneId
>>> assert pane.pane_id is not None
>>> result = run(
...     DisplayMessage(
...         target=PaneId(pane.pane_id),
...         message="#{session_id}:#{window_id}:#{pane_id}",
...     ),
...     SubprocessEngine.for_server(server),
... ).raise_for_status()
>>> result.text.split(":") == [
...     session.session_id,
...     window.window_id,
...     pane.pane_id,
... ]
True
```

## Operation reference

```{tmuxop:operation} display_message
```

## Failure and effects

This operation reads tmux state without changing it. An unknown or unavailable
format expands to an empty value; a missing target produces a failed result.

## Related operations

- {tmuxop:op}`clear_history`
- {tmuxop:op}`join_pane`
