# Execute tmux commands from a file

{class}`~libtmux.experimental.ops.SourceFile` executes tmux commands from a file
through {class}`~libtmux.experimental.engines.subprocess.SubprocessEngine` and
returns {class}`~libtmux.experimental.ops.results.AckResult`.

## Example

This executable example uses an isolated live tmux server. `server` and
`tmp_path` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import DeleteBuffer, ShowBuffer, SourceFile, run
>>> config = tmp_path / "source.conf"
>>> _ = config.write_text(
...     "set-buffer -b docs-source sourced\n",
...     encoding="utf-8",
... )
>>> engine = SubprocessEngine.for_server(server)
>>> sourced = run(SourceFile(path=str(config)), engine).raise_for_status()
>>> observed = run(
...     ShowBuffer(buffer_name="docs-source"),
...     engine,
... ).raise_for_status()
>>> proof = type(sourced).__name__, observed.text
>>> _ = run(DeleteBuffer(buffer_name="docs-source"), engine).raise_for_status()
>>> proof
('AckResult', 'sourced')
```

## Operation reference

```{tmuxop:operation} source_file
```

## Failure and effects

Commands in the file can change any state available to tmux. A missing file or
invalid command can return a failed result; call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` to raise it.
The example confines the effect to an owned buffer and removes it afterward.

## Related operations

- {tmuxop:op}`show_buffer`
- {tmuxop:op}`start_server`
