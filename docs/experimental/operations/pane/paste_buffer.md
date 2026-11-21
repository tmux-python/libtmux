# Paste a buffer into a pane

{class}`~libtmux.experimental.ops.PasteBuffer` writes a tmux paste buffer into
one pane as terminal input.

## Example

This executable example uses the injected live `server` and `pane` context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import CapturePane, PasteBuffer, SetBuffer, run
>>> from libtmux.experimental.ops._types import PaneId
>>> assert pane.pane_id is not None
>>> target = PaneId(pane.pane_id)
>>> engine = SubprocessEngine.for_server(server)
>>> _ = run(
...     SetBuffer(
...         buffer_name="docs-paste",
...         data=(
...             "printf 'docs-pasted\\n'; "
...             "tmux wait-for -S docs-paste-buffer\n"
...         ),
...     ),
...     engine,
... ).raise_for_status()
>>> result = run(
...     PasteBuffer(
...         target=target,
...         buffer_name="docs-paste",
...         delete=True,
...     ),
...     engine,
... ).raise_for_status()
>>> server.wait_for("docs-paste-buffer")
>>> captured = run(CapturePane(target=target, start=-10), engine).raise_for_status()
>>> type(result).__name__, any("docs-pasted" in line for line in captured.lines)
('AckResult', True)
```

## Operation reference

```{tmuxop:operation} paste_buffer
```

## Failure and effects

This operation writes input. `delete=True` removes the buffer after a successful
paste; `bracket=True` asks applications that support bracketed paste to treat
the text as one paste event.

## Related operations

- {tmuxop:op}`move_pane`
- {tmuxop:op}`pipe_pane`
