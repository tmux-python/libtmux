# Load a paste buffer from a file

{class}`~libtmux.experimental.ops.LoadBuffer` reads a file into a paste buffer
through {class}`~libtmux.experimental.engines.subprocess.SubprocessEngine` and
returns {class}`~libtmux.experimental.ops.results.AckResult`.

## Example

This executable example uses an isolated live tmux server. `server` and
`tmp_path` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import DeleteBuffer, LoadBuffer, ShowBuffer, run
>>> source = tmp_path / "buffer.txt"
>>> _ = source.write_text("loaded from file", encoding="utf-8")
>>> engine = SubprocessEngine.for_server(server)
>>> loaded = run(
...     LoadBuffer(path=str(source), buffer_name="docs-load"),
...     engine,
... ).raise_for_status()
>>> observed = run(
...     ShowBuffer(buffer_name="docs-load"),
...     engine,
... ).raise_for_status()
>>> proof = type(loaded).__name__, observed.text
>>> _ = run(DeleteBuffer(buffer_name="docs-load"), engine).raise_for_status()
>>> proof
('AckResult', 'loaded from file')
```

## Operation reference

```{tmuxop:operation} load_buffer
```

## Failure and effects

A missing or unreadable path returns a failed result. Call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` to raise it.
The loaded buffer persists until it is replaced or deleted; the example owns
and removes its named buffer.

## Related operations

- {tmuxop:op}`list_windows`
- {tmuxop:op}`new_session`
