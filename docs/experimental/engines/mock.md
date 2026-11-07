# Mock engine

{class}`~libtmux.experimental.engines.mock.MockEngine` is a synchronous,
in-memory command simulator.

## Use it when

Use it to test operation rendering, typed result conversion, fabricated create
IDs, and deterministic captured pane content without starting tmux.

## Avoid it when

Do not use it to prove target existence, server state, version behavior,
permissions, shell execution, transport failures, or tmux output parsing.

## Construction and cleanup

Pass optional canned `capture_lines`. An instance keeps only monotonic ID
counters and needs no cleanup.

The result below is canned. The engine does not contact tmux or inspect whether
the target pane exists.

```python
>>> from libtmux.experimental.engines import MockEngine
>>> from libtmux.experimental.ops import CapturePane, PaneId, run
>>> engine = MockEngine(capture_lines=("canned, no tmux",))
>>> canned = run(
...     CapturePane(target=PaneId("%404")),
...     engine,
... ).raise_for_status()
>>> canned.lines
('canned, no tmux',)
```

## Lifecycle and failure boundary

Create commands that request formatted IDs receive fabricated IDs.
`capture-pane` receives the configured lines; every other command succeeds with
empty output. The simulator does not track whether fabricated sessions,
windows, or panes exist.
{meth}`~libtmux.experimental.engines.mock.MockEngine.run_batch` is an ordered
loop with no batching benefit.

## API

```{eval-rst}
.. autoclass:: libtmux.experimental.engines.mock.MockEngine
   :members:
```

## Related tutorial

See {doc}`../tutorials/offline-testing` for the claims an offline engine can and
cannot support.
