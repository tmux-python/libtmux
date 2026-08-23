# Capture pane output

{class}`~libtmux.experimental.ops.CapturePane` reads the visible pane and
scrollback into typed output lines.

## Example

This executable example uses the injected live `server` and `pane` context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import CapturePane, SendKeys, run
>>> from libtmux.experimental.ops._types import PaneId
>>> assert pane.pane_id is not None
>>> target = PaneId(pane.pane_id)
>>> engine = SubprocessEngine.for_server(server)
>>> _ = run(
...     SendKeys(
...         target=target,
...         keys="printf 'docs-captured\\n'; tmux wait-for -S docs-capture",
...         enter=True,
...     ),
...     engine,
... ).raise_for_status()
>>> server.wait_for("docs-capture")
>>> result = run(CapturePane(target=target, start=-10), engine).raise_for_status()
>>> type(result).__name__, any("docs-captured" in line for line in result.lines)
('CapturePaneResult', True)
```

## Operation reference

```{tmuxop:operation} capture_pane
```

## Failure and effects

This operation reads terminal output without changing tmux state. It is safe to
repeat.

The `trim_trailing` flag is available on tmux 3.4 and newer; `mode_screen`
requires tmux 3.6. The operation omits an unavailable optional flag when you
provide an older tmux version.

## Related operations

- {tmuxop:op}`swap_pane`
- {tmuxop:op}`clear_history`
