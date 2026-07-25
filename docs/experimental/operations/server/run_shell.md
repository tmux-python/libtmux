# Run a shell command via tmux

{class}`~libtmux.experimental.ops.RunShell` asks tmux to execute a shell command
through {class}`~libtmux.experimental.engines.subprocess.SubprocessEngine` and
returns {class}`~libtmux.experimental.ops.results.AckResult`.

## Example

This executable example uses an isolated live tmux server. `server` and
`tmp_path` are injected documentation context.

```python
>>> import shlex
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import RunShell, run
>>> destination = tmp_path / "run-shell.txt"
>>> command = f"printf ready > {shlex.quote(str(destination))}"
>>> result = run(
...     RunShell(command_line=command),
...     SubprocessEngine.for_server(server),
... ).raise_for_status()
>>> type(result).__name__, destination.read_text(encoding="utf-8")
('AckResult', 'ready')
```

## Operation reference

```{tmuxop:operation} run_shell
```

## Failure and effects

The command runs with the tmux server process's privileges and may change
external state. Without `background=True`, the acknowledgement arrives after
the command finishes, so the example can read its private file directly.
Background execution needs a bounded state poll rather than an arbitrary
delay.

## Related operations

- {tmuxop:op}`new_session`
- {tmuxop:op}`save_buffer`
