# Set the contents of a paste buffer

{class}`~libtmux.experimental.ops.SetBuffer` creates or updates a paste buffer
through {class}`~libtmux.experimental.engines.subprocess.SubprocessEngine` and
returns {class}`~libtmux.experimental.ops.results.AckResult`.

## Example

This executable example uses an isolated live tmux server. `server`, `session`,
`window`, and `pane` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import DeleteBuffer, SetBuffer, ShowBuffer, run
>>> engine = SubprocessEngine.for_server(server)
>>> changed = run(
...     SetBuffer(buffer_name="docs-set", data="live buffer"),
...     engine,
... ).raise_for_status()
>>> observed = run(
...     ShowBuffer(buffer_name="docs-set"),
...     engine,
... ).raise_for_status()
>>> proof = type(changed).__name__, observed.text
>>> _ = run(DeleteBuffer(buffer_name="docs-set"), engine).raise_for_status()
>>> proof
('AckResult', 'live buffer')
```

## Operation reference

```{tmuxop:operation} set_buffer
```

## Failure and effects

Setting a named buffer replaces its contents unless `append=True`. The
acknowledgement proves dispatch; the independent
{class}`~libtmux.experimental.ops.ShowBuffer` read proves the stored text. The
example removes the buffer it creates.

## Related operations

- {tmuxop:op}`save_buffer`
- {tmuxop:op}`show_buffer`
