# Engine tutorials

These task guides share setup, result handling, and lifecycle details that apply
across operation pages and concrete engine references.

- {doc}`live-operation` starts with a private server or the injected
  documentation fixtures.
- {doc}`results-and-failures` separates typed success, command failure, expected
  absence, version rejection, and skipped work.
- {doc}`async-subprocess` runs independent operations concurrently without
  blocking the event loop.
- {doc}`control-mode` uses persistent sync and async connections safely.
- {doc}`offline-testing` tests rendering and result conversion without tmux.
- {doc}`imsg-parity` binds both native and CLI engines to the same server for a
  narrow comparison.

```{toctree}
:hidden:

live-operation
results-and-failures
async-subprocess
control-mode
offline-testing
imsg-parity
```
