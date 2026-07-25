# Delete a paste buffer

{class}`~libtmux.experimental.ops.DeleteBuffer` removes one paste buffer through
{class}`~libtmux.experimental.engines.subprocess.SubprocessEngine` and returns
{class}`~libtmux.experimental.ops.results.AckResult`.

## Example

This executable example uses an isolated live tmux server. `server`, `session`,
`window`, and `pane` are injected documentation context.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import DeleteBuffer, SetBuffer, ShowBuffer, run
>>> engine = SubprocessEngine.for_server(server)
>>> _ = run(
...     SetBuffer(buffer_name="docs-delete", data="temporary"),
...     engine,
... ).raise_for_status()
>>> before = run(
...     ShowBuffer(buffer_name="docs-delete"),
...     engine,
... ).raise_for_status()
>>> deleted = run(
...     DeleteBuffer(buffer_name="docs-delete"),
...     engine,
... ).raise_for_status()
>>> after = run(ShowBuffer(buffer_name="docs-delete"), engine)
>>> type(deleted).__name__, before.text, after.ok, bool(after.stderr)
('AckResult', 'temporary', False, True)
```

## Operation reference

```{tmuxop:operation} delete_buffer
```

## Failure and effects

Omitting `buffer_name` deletes tmux's most recent buffer. Prefer an explicit,
owned name when cleanup must be predictable. Deleting or showing a missing
named buffer returns a failed result; call
{meth}`~libtmux.experimental.ops.results.Result.raise_for_status` to raise it.

## Related operations

- {tmuxop:op}`start_server`
- {tmuxop:op}`kill_server`
