# Subprocess engine

{class}`~libtmux.experimental.engines.subprocess.SubprocessEngine` runs each
request through a new tmux CLI process.

## Use it when

Use this engine for synchronous live-server work, especially when independent
process lifetime and the classic tmux CLI path are useful defaults.

## Avoid it when

Choose control mode when a large batch should share one connection. Choose an
async engine when blocking process I/O would stall an event loop.

## Construction and cleanup

Construct the engine with explicit `tmux_bin` and `server_args`, or use
{meth}`~libtmux.experimental.engines.subprocess.SubprocessEngine.for_server` to
copy a live {class}`~libtmux.Server` connection. The engine retains no child
process and has no cleanup method.

```python
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import ListSessions, run
>>> engine = SubprocessEngine.for_server(server)
>>> result = run(ListSessions(), engine).raise_for_status()
>>> any(item.session_id == session.session_id for item in result.sessions)
True
```

## Lifecycle and failure boundary

{meth}`~libtmux.experimental.engines.subprocess.SubprocessEngine.run` starts,
communicates with, and reaps one child.
{meth}`~libtmux.experimental.engines.subprocess.SubprocessEngine.run_batch`
repeats that sequence in request order, so it does not pipeline. A tmux
rejection is returned as raw command data and becomes a failed operation result.
A missing tmux executable raises {exc}`libtmux.exc.TmuxCommandNotFound`.

## API

```{eval-rst}
.. autoclass:: libtmux.experimental.engines.subprocess.SubprocessEngine
   :members:
```

## Related tutorial

See {doc}`../tutorials/live-operation` for standalone and test-fixture server
setup.
