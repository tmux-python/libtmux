# Pipe pane output to a command

{class}`~libtmux.experimental.ops.PipePane` streams new output from one pane to
a shell command until you close or replace the pipe.

## Example

This executable example uses the injected live `server`, `pane`, and
`tmp_path` context. The output file belongs to the documentation sandbox.

```python
>>> import shlex
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import PipePane, SendKeys, run
>>> from libtmux.experimental.ops._types import PaneId
>>> from libtmux.test.retry import retry_until
>>> output = tmp_path / "pane-output.txt"
>>> assert pane.pane_id is not None
>>> target = PaneId(pane.pane_id)
>>> engine = SubprocessEngine.for_server(server)
>>> opened = run(
...     PipePane(
...         target=target,
...         command_line=f"cat > {shlex.quote(str(output))}",
...     ),
...     engine,
... ).raise_for_status()
>>> _ = run(
...     SendKeys(
...         target=target,
...         keys="printf 'docs-pipe\\n'; tmux wait-for -S docs-pipe-pane",
...         enter=True,
...     ),
...     engine,
... ).raise_for_status()
>>> server.wait_for("docs-pipe-pane")
>>> closed = run(PipePane(target=target), engine).raise_for_status()
>>> observed = retry_until(
...     lambda: output.exists()
...     and "docs-pipe" in output.read_text(encoding="utf-8"),
...     seconds=2,
... )
>>> type(opened).__name__, type(closed).__name__, observed
('AckResult', 'AckResult', True)
```

## Operation reference

```{tmuxop:operation} pipe_pane
```

## Failure and effects

Calling the operation without `command_line` closes the current pipe. The
consumer command controls buffering and file semantics; the example closes the
pipe before reading its owned file.

## Related operations

- {tmuxop:op}`paste_buffer`
- {tmuxop:op}`resize_pane`
