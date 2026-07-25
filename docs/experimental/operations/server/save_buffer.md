# Save a paste buffer to a file

{class}`~libtmux.experimental.ops.SaveBuffer` writes a paste buffer to a file
through {class}`~libtmux.experimental.engines.subprocess.SubprocessEngine` and
returns {class}`~libtmux.experimental.ops.results.AckResult`.

## Example

This executable example uses an isolated live tmux server. `server` and
`tmp_path` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import DeleteBuffer, SaveBuffer, SetBuffer, run
>>> destination = tmp_path / "saved.txt"
>>> engine = SubprocessEngine.for_server(server)
>>> _ = run(
...     SetBuffer(buffer_name="docs-save", data="saved by tmux"),
...     engine,
... ).raise_for_status()
>>> saved = run(
...     SaveBuffer(path=str(destination), buffer_name="docs-save"),
...     engine,
... ).raise_for_status()
>>> proof = type(saved).__name__, destination.read_text(encoding="utf-8")
>>> _ = run(DeleteBuffer(buffer_name="docs-save"), engine).raise_for_status()
>>> proof
('AckResult', 'saved by tmux')
```

## Operation reference

```{tmuxop:operation} save_buffer
```

## Failure and effects

Saving reads tmux state but writes to the filesystem. It replaces the
destination by default; `append=True` extends it instead. A missing buffer or
unwritable path returns a failed result. The example confines both resources to
an owned buffer and pytest's private temporary directory.

## Related operations

- {tmuxop:op}`run_shell`
- {tmuxop:op}`set_buffer`
