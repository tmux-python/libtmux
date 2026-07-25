# Send input to a pane

{class}`~libtmux.experimental.ops.SendKeys` types keys into a pane, optionally
pressing Enter after the input.

## Example

This executable example uses the injected live `server` and `pane` context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import CapturePane, SendKeys, run
>>> from libtmux.experimental.ops._types import PaneId
>>> assert pane.pane_id is not None
>>> target = PaneId(pane.pane_id)
>>> engine = SubprocessEngine.for_server(server)
>>> result = run(
...     SendKeys(
...         target=target,
...         keys="printf 'docs-ready\\n'; tmux wait-for -S docs-send-keys",
...         enter=True,
...     ),
...     engine,
... ).raise_for_status()
>>> server.wait_for("docs-send-keys")
>>> captured = run(CapturePane(target=target, start=-10), engine).raise_for_status()
>>> type(result).__name__, any("docs-ready" in line for line in captured.lines)
('AckResult', True)
```

## Operation reference

```{tmuxop:operation} send_keys
```

## Failure and effects

This operation changes tmux state and writes input. `literal=True` cannot be
combined with `enter=True`: tmux's literal mode would type the word `Enter`
instead of pressing Return.

## Related operations

- {tmuxop:op}`select_pane`
- {tmuxop:op}`swap_pane`
