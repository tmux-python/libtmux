# Execution engines

Operations declare tmux commands and convert their output to typed results.
Engines own dispatch: transport, concurrency, process or connection lifetime,
batching, and transport-level failures. Changing the engine does not change the
operation or its result type, but it does change the resources and failure
boundary around execution.

## Choose an engine

| Engine                                                                                                                        | Dispatch model                                        | Use it for                                                  |
| ----------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- | ----------------------------------------------------------- |
| {class}`~libtmux.experimental.engines.subprocess.SubprocessEngine` ([reference](engines/subprocess.md))                       | One tmux CLI process per request                      | Straightforward synchronous live-server work                |
| {class}`~libtmux.experimental.engines.asyncio.AsyncSubprocessEngine` ([reference](engines/async-subprocess.md))               | One asyncio subprocess per request                    | Async applications that do not need a persistent connection |
| {class}`~libtmux.experimental.engines.mock.MockEngine` ([reference](engines/mock.md))                                         | Stateless in-memory simulation                        | Offline rendering and result-conversion tests               |
| {class}`~libtmux.experimental.engines.mock.AsyncMockEngine` ([reference](engines/async-mock.md))                              | Async stateless in-memory simulation                  | Offline tests of async callers                              |
| {class}`~libtmux.experimental.engines.control_mode.ControlModeEngine` ([reference](engines/control-mode.md))                  | Subprocess bootstrap, then persistent `tmux -C`       | Pipelined command batches                                   |
| {class}`~libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine` ([reference](engines/async-control-mode.md)) | Async subprocess bootstrap, then supervised `tmux -C` | Async batches and control-mode notifications                |
| {class}`~libtmux.experimental.engines.imsg.base.ImsgEngine` ([reference](engines/imsg.md))                                    | Native socket with required CLI fallbacks             | POSIX protocol experiments and narrow parity checks         |

The control-mode engines open a persistent client only when an existing
session has `destroy-unattached` set to `off`. Until then, they use their
matching subprocess engine so a user command can create the first safe session.

## Select by name

The registry exposes the synchronous engine families.
Async engines are constructed directly. Their lifecycle belongs to the caller's
event loop.

```python
>>> from libtmux.experimental.engines import available_engines, create_engine
>>> from libtmux.experimental.ops import HasSession, run
>>> from libtmux.experimental.ops._types import SessionId
>>> available_engines()
('control_mode', 'imsg', 'mock', 'subprocess')
>>> engine = create_engine("mock")
>>> run(HasSession(target=SessionId("$0")), engine).status
'complete'
```

## Engine boundary

A synchronous engine satisfies
{class}`~libtmux.experimental.engines.base.TmuxEngine`; an async engine
satisfies {class}`~libtmux.experimental.engines.base.AsyncTmuxEngine`. Both
accept a {class}`~libtmux.experimental.engines.base.CommandRequest` and produce
a raw {class}`~libtmux.experimental.engines.base.CommandResult`.
{func}`~libtmux.experimental.ops.run` and
{func}`~libtmux.experimental.ops.arun` own the next boundary: they render an
operation and convert the raw command outcome to its declared typed result.

A tmux command rejection is normally result data. Missing executables, dead
persistent connections, protocol mismatches, and similar transport failures
raise at the engine boundary.

## Tutorials

Start with {doc}`tutorials/live-operation`, then use the task guide that matches
the boundary you need to understand:

- {doc}`tutorials/results-and-failures`
- {doc}`tutorials/async-subprocess`
- {doc}`tutorials/control-mode`
- {doc}`tutorials/offline-testing`
- {doc}`tutorials/imsg-parity`

## Shared API

```{eval-rst}
.. autoclass:: libtmux.experimental.engines.base.TmuxEngine
   :members:

.. autoclass:: libtmux.experimental.engines.base.AsyncTmuxEngine
   :members:

.. autoclass:: libtmux.experimental.engines.base.CommandRequest
   :members:

.. autoclass:: libtmux.experimental.engines.base.CommandResult
   :members:

.. autofunction:: libtmux.experimental.engines.registry.available_engines

.. autofunction:: libtmux.experimental.engines.registry.create_engine
```

```{toctree}
:hidden:

engines/subprocess
engines/async-subprocess
engines/mock
engines/async-mock
engines/control-mode
engines/async-control-mode
engines/imsg
tutorials/index
```
