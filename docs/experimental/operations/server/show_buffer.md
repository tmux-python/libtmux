# Show the contents of a paste buffer

{class}`~libtmux.experimental.ops.ShowBuffer` reads one paste buffer through
{class}`~libtmux.experimental.engines.subprocess.SubprocessEngine` and returns
its text in {class}`~libtmux.experimental.ops.results.ShowBufferResult`.

## Example

This executable example uses an isolated live tmux server. `server`, `session`,
`window`, and `pane` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import DeleteBuffer, SetBuffer, ShowBuffer, run
>>> engine = SubprocessEngine.for_server(server)
>>> _ = run(
...     SetBuffer(buffer_name="docs-show", data="buffer contents"),
...     engine,
... ).raise_for_status()
>>> result = run(ShowBuffer(buffer_name="docs-show"), engine).raise_for_status()
>>> proof = type(result).__name__, result.text
>>> _ = run(DeleteBuffer(buffer_name="docs-show"), engine).raise_for_status()
>>> proof
('ShowBufferResult', 'buffer contents')
```

## Operation reference

```{tmuxop:operation} show_buffer
```

## Failure and effects

Showing a missing named buffer returns a failed result. Call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` to raise that
error. The read itself does not change tmux state; the example owns and removes
its setup buffer.

## Related operations

- {tmuxop:op}`set_buffer`
- {tmuxop:op}`source_file`
